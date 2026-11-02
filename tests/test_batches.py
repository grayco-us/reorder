"""Batch regression tests using real Home Assistant services and mocked Zinc I/O."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Avoid the optional model-price download in Home Assistant's unrelated AI helper.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import SOURCE_USER
from homeassistant.exceptions import HomeAssistantError

from custom_components.reorder.batch import create_batch
from custom_components.reorder.store import ReorderStore
from custom_components.reorder.zinc import ZincClient


def order(index=1):
    return {
        "id": str(index), "product_key": f"product {index}", "name": f"Product {index}",
        "retailer": "zinc", "product_id": f"https://example.com/product/{index}",
        "quantity": 2, "max_price": 12.5, "status": "queued",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


class BatchActionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        custom = Path(self.directory.name, "custom_components")
        custom.mkdir()
        (custom / "reorder").symlink_to(Path(__file__).resolve().parents[1] / "custom_components/reorder", target_is_directory=True)
        self.hass = HomeAssistant(self.directory.name)
        self.addAsyncCleanup(self.hass.async_stop)
        # Discovery is unrelated to Reorder; avoid multicast sockets and HA's
        # process-global Zeroconf constructor patch across isolated event loops.
        discovery_patch = patch("homeassistant.components.zeroconf.async_setup", AsyncMock(return_value=True))
        discovery_patch.start()
        self.addCleanup(discovery_patch.stop)
        zeroconf_patch = patch("homeassistant.components.zeroconf._async_get_instance", return_value=MagicMock())
        zeroconf_patch.start()
        self.addCleanup(zeroconf_patch.stop)
        loader.async_setup(self.hass)
        assert await bootstrap.async_from_config_dict({
            "homeassistant": {"latitude": 0, "longitude": 0, "elevation": 0,
                              "time_zone": "America/New_York", "unit_system": "metric"},
            "persistent_notification": {},
        }, self.hass)
        await self.hass.async_start()
        self.transport = AsyncMock(return_value={"id": "mock-zinc-id", "status": "submitted"})
        transport_patch = patch.object(ZincClient, "request", self.transport)
        transport_patch.start()
        self.addCleanup(transport_patch.stop)
        def track_interval(hass, action, interval):
            self.scheduled = action
            return callback(lambda: None)
        scheduler_patch = patch("custom_components.reorder.async_track_time_interval", side_effect=track_interval)
        scheduler_patch.start()
        self.addCleanup(scheduler_patch.stop)
        result = await self.hass.config_entries.flow.async_init("reorder", context={"source": SOURCE_USER}, data={})
        await self.hass.async_block_till_done()
        self.entry = result["result"]
        assert self.entry.state.value == "loaded"
        self.engine = self.hass.data["reorder"][self.entry.entry_id]
        self.engine.store.data["orders"] = {"1": order()}
        await self.engine.store.save()
        self.options = {"zinc_api_key": "zn_test_not-a-real-key"}
        self.options.update({"ship_" + field: "test-only" for field in (
            "first_name", "last_name", "address_line1", "city", "state", "postal_code", "phone_number")})
        self.hass.config_entries.async_update_entry(self.entry, options=self.options)

    async def call(self, service, data=None, response=False):
        return await self.hass.services.async_call("reorder", service, data or {}, blocking=True, return_response=response)

    async def prepare(self):
        return await self.call("prepare_batch", response=True)

    async def submit(self, batch, confirmation="SANDBOX"):
        await self.call("submit_batch_zinc", {"batch_id": batch["id"], "confirmation": confirmation})

    async def test_preview_returns_report_without_mutating_storage(self):
        before = deepcopy(self.engine.store.data)
        report = await self.call("preview_batch", response=True)
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["price_ceiling"], 12.5)
        self.assertEqual(self.engine.store.data, before)
        self.assertIn("reorder_batch_preview", self.hass.data["persistent_notification"])
        self.transport.assert_not_awaited()

    async def test_schedule_notification_failure_does_not_duplicate_or_purchase(self):
        self.engine.store.data["batch_settings"]["strategy"] = "rolling"
        with patch("custom_components.reorder.notifications.persistent_notification.async_create", side_effect=RuntimeError("display failed")):
            with self.assertLogs("custom_components.reorder", level="WARNING"):
                await self.scheduled(None)
        await self.scheduled(None)
        self.assertEqual(len(self.engine.store.data["batches"]), 1)
        self.assertIn("last_scheduled_date", self.engine.store.data["batch_settings"])
        self.transport.assert_not_awaited()

    async def test_empty_preview(self):
        self.engine.store.data["orders"].clear()
        self.assertEqual((await self.call("preview_batch", response=True))["count"], 0)

    async def test_prepare_persists_batch_and_updates_sensor(self):
        batch = await self.prepare()
        await self.hass.async_block_till_done()
        self.assertEqual(batch["status"], "ready")
        self.assertEqual(self.engine.store.data["orders"]["1"]["batch_id"], batch["id"])
        restored = ReorderStore(self.hass)
        await restored.load()
        self.assertEqual(restored.data["batches"][batch["id"]], batch)
        sensor = self.hass.states.get("sensor.prepared_batches")
        self.assertEqual(sensor.state, "1")
        self.assertEqual(sensor.attributes["batches"][0]["id"], batch["id"])
        self.transport.assert_not_awaited()

    async def test_notification_failure_does_not_fail_preview_or_preparation(self):
        with patch("custom_components.reorder.notifications.persistent_notification.async_create", side_effect=RuntimeError("display failed")):
            with self.assertLogs("custom_components.reorder", level="WARNING"):
                self.assertEqual((await self.call("preview_batch", response=True))["count"], 1)
                batch = await self.prepare()
        self.assertIn(batch["id"], self.engine.store.data["batches"])
        self.transport.assert_not_awaited()

    async def test_prepare_without_response_remains_supported(self):
        await self.call("prepare_batch")
        self.assertEqual(len(self.engine.store.data["batches"]), 1)

    async def test_repeated_and_concurrent_prepare_do_not_duplicate(self):
        results = await asyncio.gather(self.prepare(), self.prepare(), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(isinstance(r, HomeAssistantError) for r in results), 1)
        with self.assertRaisesRegex(HomeAssistantError, "No eligible"):
            await self.prepare()
        self.assertEqual(len(self.engine.store.data["batches"]), 1)
        self.transport.assert_not_awaited()

    async def test_prepare_after_reload_does_not_duplicate(self):
        batch = await self.prepare()
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        with self.assertRaisesRegex(HomeAssistantError, "No eligible"):
            await self.prepare()
        self.assertEqual(list(self.hass.data["reorder"][self.entry.entry_id].store.data["batches"]), [batch["id"]])

    async def test_prepare_limits_batches_to_disjoint_orders(self):
        self.engine.store.data["orders"]["2"] = order(2)
        first = await self.call("prepare_batch", {"max_items": 1}, response=True)
        second = await self.prepare()
        self.assertTrue(set(first["order_ids"]).isdisjoint(second["order_ids"]))

    async def test_prepare_rejects_duplicate_products(self):
        duplicate = order(2)
        duplicate["product_key"] = "product 1"
        self.engine.store.data["orders"]["2"] = duplicate
        with self.assertRaisesRegex(HomeAssistantError, "Duplicate"):
            await self.prepare()
        self.assertEqual(self.engine.store.data["batches"], {})

    async def test_prepare_save_failure_rolls_back_memory(self):
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await create_batch(self.engine)
        self.assertEqual(self.engine.store.data["batches"], {})
        self.assertNotIn("batch_id", self.engine.store.data["orders"]["1"])
        self.transport.assert_not_awaited()

    async def test_submit_persists_before_network_and_uses_stable_key(self):
        batch = await self.prepare()
        async def request(method, path, payload):
            stored = ReorderStore(self.hass)
            await stored.load()
            self.assertEqual(stored.data["batches"][batch["id"]]["status"], "submitting")
            self.assertEqual(stored.data["orders"]["1"]["status"], "submitting")
            self.assertEqual((method, path), ("POST", "/orders"))
            self.assertEqual(payload["idempotency_key"], "reorder-batch-" + batch["id"])
            self.assertEqual(payload["max_price"], 1250)
            self.assertEqual(payload["products"], [{"url": order()["product_id"], "quantity": 2}])
            return {"id": "mock-zinc-id", "status": "submitted"}
        self.transport.side_effect = request
        await self.submit(batch)
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.transport.assert_awaited_once()

    async def test_concurrent_submit_calls_network_once(self):
        batch = await self.prepare()
        results = await asyncio.gather(self.submit(batch), self.submit(batch), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, HomeAssistantError) for r in results), 1)
        self.transport.assert_awaited_once()

    async def test_timeout_blocks_retry_and_individual_submission(self):
        batch = await self.prepare()
        self.transport.side_effect = TimeoutError("simulated uncertainty")
        with self.assertRaises(TimeoutError):
            await self.submit(batch)
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "submission_unknown")
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        with self.assertRaises(HomeAssistantError):
            await self.call("submit_zinc", {"order_id": "1", "confirmation": "SANDBOX"})
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.transport.assert_awaited_once()

    async def test_malformed_response_is_uncertain_and_cannot_retry(self):
        batch = await self.prepare()
        self.transport.return_value = {}
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "submission_unknown")
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.transport.assert_awaited_once()

    async def test_provider_ready_status_cannot_reopen_submission(self):
        batch = await self.prepare()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "ready"}
        await self.submit(batch)
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.transport.assert_awaited_once()

    async def test_submit_storage_failure_never_calls_network(self):
        batch = await self.prepare()
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_uncertain_product_order_blocks_batch_purchase(self):
        batch = await self.prepare()
        duplicate = order(2)
        duplicate.update(product_key="product 1", status="submission_unknown")
        self.engine.store.data["orders"]["2"] = duplicate
        with self.assertRaisesRegex(HomeAssistantError, "active or uncertain"):
            await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_confirmation_and_credential_guards(self):
        batch = await self.prepare()
        cases = [
            ({}, "SANDBOX"),
            ({"zinc_api_key": "invalid-test-only"}, "SANDBOX"),
            ({"zinc_api_key": "zn_live_not-a-real-key"}, "PLACE LIVE ORDER"),
            ({"zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True}, "SANDBOX"),
            ({"zinc_api_key": "zn_test_not-a-real-key"}, "PLACE LIVE ORDER"),
        ]
        for override, confirmation in cases:
            with self.subTest(override=override, confirmation=confirmation):
                options = self.options | override
                if not override:
                    options.pop("zinc_api_key")
                self.hass.config_entries.async_update_entry(self.entry, options=options)
                with self.assertRaises(HomeAssistantError):
                    await self.submit(batch, confirmation)
        self.transport.assert_not_awaited()

    async def test_explicit_live_confirmation_with_synthetic_key_uses_mock_only(self):
        batch = await self.prepare()
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {
            "zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True,
        })
        await self.submit(batch, "PLACE LIVE ORDER")
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["zinc_environment"], "live")
        self.transport.assert_awaited_once()

    async def test_sandbox_batch_cannot_refresh_with_live_settings(self):
        batch = await self.prepare()
        await self.submit(batch)
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {
            "zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True,
        })
        with self.assertRaisesRegex(HomeAssistantError, "current environment"):
            await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.transport.assert_awaited_once()

    async def test_attempted_single_order_cannot_submit_or_enter_a_batch_again(self):
        self.transport.return_value = {"id": "mock-zinc-id", "status": "queued"}
        await self.call("submit_zinc", {"order_id": "1", "confirmation": "SANDBOX"})
        with self.assertRaises(HomeAssistantError):
            await self.call("submit_zinc", {"order_id": "1", "confirmation": "SANDBOX"})
        self.assertEqual((await self.call("preview_batch", response=True))["count"], 0)
        with self.assertRaisesRegex(HomeAssistantError, "No eligible"):
            await self.prepare()
        self.transport.assert_awaited_once()

    async def test_submit_response_and_notification_identify_saved_batch(self):
        batch = await self.prepare()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "pending"}
        report = await self.call("submit_batch_zinc", {
            "batch_id": batch["id"], "confirmation": "SANDBOX",
        }, response=True)
        self.assertEqual(report["id"], batch["id"])
        self.assertEqual(report["status"], "pending")
        notification = self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"]
        self.assertIn("Sandbox simulation", notification["message"])
        self.assertIn("pending", notification["message"])
        self.assertEqual(notification["title"], "Reorder — Batch Submitted")
        self.transport.assert_awaited_once()

    async def test_refresh_returns_saved_status_and_updates_notification(self):
        batch = await self.prepare()
        await self.submit(batch)
        self.transport.reset_mock()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed"}
        report = await self.call("refresh_batch_zinc", {"batch_id": batch["id"]}, response=True)
        self.transport.assert_awaited_once_with("GET", "/orders/mock-zinc-id")
        self.assertEqual(report["status"], "order_placed")
        self.assertEqual(report["zinc_environment"], "sandbox")
        self.assertIn("last_refreshed_at", report)
        self.assertEqual(self.engine.store.data["orders"]["1"]["status"], "order_placed")
        restored = ReorderStore(self.hass)
        await restored.load()
        self.assertEqual(restored.data["batches"][batch["id"]], report)
        notification = self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"]
        self.assertIn("order_placed", notification["message"])
        self.assertEqual(notification["title"], "Reorder — Batch Refreshed")

    async def test_status_notifications_cannot_fail_saved_actions(self):
        batch = await self.prepare()
        with patch("custom_components.reorder.notifications.persistent_notification.async_create", side_effect=RuntimeError("display failed")):
            with self.assertLogs("custom_components.reorder", level="WARNING"):
                submitted = await self.call("submit_batch_zinc", {
                    "batch_id": batch["id"], "confirmation": "SANDBOX",
                }, response=True)
                self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed"}
                refreshed = await self.call("refresh_batch_zinc", {"batch_id": batch["id"]}, response=True)
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(refreshed["status"], "order_placed")
        self.assertEqual(len(self.engine.store.data["batches"]), 1)

    async def test_refresh_error_preserves_state_and_previous_notification(self):
        batch = await self.prepare()
        await self.submit(batch)
        before = deepcopy(self.engine.store.data)
        notification = deepcopy(self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"])
        self.transport.side_effect = HomeAssistantError("Zinc returned HTTP 503")
        with self.assertRaisesRegex(HomeAssistantError, "503"):
            await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data, before)
        self.assertEqual(self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"], notification)

    async def test_malformed_refresh_does_not_replace_known_status(self):
        batch = await self.prepare()
        await self.submit(batch)
        before = deepcopy(self.engine.store.data)
        for response in ({}, [], {"status": None}, {"status": ""}, {"id": "another-order", "status": "order_placed"}):
            with self.subTest(response=response):
                self.transport.return_value = response
                with self.assertRaises(HomeAssistantError):
                    await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
                self.assertEqual(self.engine.store.data, before)

    async def test_ready_batch_refresh_requires_zinc_id(self):
        batch = await self.prepare()
        # A never-submitted batch has no matching Zinc environment.
        with self.assertRaisesRegex(HomeAssistantError, "current environment"):
            await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.transport.assert_not_awaited()

    async def test_pending_order_blocks_another_purchase_for_same_product(self):
        batch = await self.prepare()
        previous = order(2) | {"product_key": "product 1", "status": "pending"}
        self.engine.store.data["orders"]["2"] = previous
        with self.assertRaisesRegex(HomeAssistantError, "active or uncertain"):
            await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_refresh_failure_status_does_not_enable_resubmission(self):
        batch = await self.prepare()
        await self.submit(batch)
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_failed"}
        report = await self.call("refresh_batch_zinc", {"batch_id": batch["id"]}, response=True)
        self.assertEqual(report["status"], "order_failed")
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.assertEqual(self.transport.await_count, 2)

    async def test_single_order_explicit_stock_failure_supports_v2_and_legacy_codes(self):
        saved = self.engine.store.data["orders"]["1"]
        saved.update(zinc_order_id="mock-zinc-id", zinc_environment="sandbox")
        for status, code in (("failed", "out_of_stock"), ("order_failed", "product_out_of_stock")):
            self.transport.return_value = {"status": status, "error_code": code}
            await self.call("refresh_zinc", {"order_id": "1"})
            self.assertEqual(saved["status"], "out_of_stock")
            self.assertEqual(len(self.engine.store.data["orders"]), 1)

    async def test_item_error_alone_never_enables_a_replacement(self):
        saved = self.engine.store.data["orders"]["1"]
        saved.update(zinc_order_id="mock-zinc-id", zinc_environment="sandbox")
        self.transport.return_value = {"status": "order_failed", "items": [{"error_type": "product_out_of_stock"}]}
        await self.call("refresh_zinc", {"order_id": "1"})
        self.assertEqual(saved["status"], "order_failed")
        with self.assertRaisesRegex(HomeAssistantError, "confirmed out of stock"):
            await self.call("queue_next_substitution", {"order_id": "1"})

    async def test_review_uses_saved_products_without_mutating_storage(self):
        batch = await self.prepare()
        self.engine.store.data["products"]["product 1"] = {"name": "Edited catalog", "quantity": 9}
        before = deepcopy(self.engine.store.data)
        report = await self.call("review_batch", {"batch_id": batch["id"]}, response=True)
        self.assertEqual(report["orders"][0]["name"], "Product 1")
        self.assertEqual(report["orders"][0]["quantity"], 2)
        self.assertEqual(report["orders"][0]["product_id"], order()["product_id"])
        self.assertEqual(self.engine.store.data, before)
        report["order_ids"].clear()
        report["orders"][0]["quantity"] = 99
        self.assertEqual(self.engine.store.data, before)
        notification = self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"]
        self.assertIn("quantity 2", notification["message"])
        self.assertEqual(notification["title"], "Reorder — Batch Review")
        self.transport.assert_not_awaited()

    async def test_review_submitted_batch_does_not_contact_zinc(self):
        batch = await self.prepare()
        await self.submit(batch)
        self.transport.reset_mock()
        await self.call("review_batch", {"batch_id": batch["id"]})
        self.transport.assert_not_awaited()

    async def test_unknown_batch_actions_report_error_without_changes(self):
        before = deepcopy(self.engine.store.data)
        for action in ("review_batch", "cancel_batch"):
            with self.assertRaisesRegex(HomeAssistantError, "Batch not found"):
                await self.call(action, {"batch_id": "missing"})
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def test_cancel_persists_batch_and_order_and_updates_sensor(self):
        batch = await self.prepare()
        report = await self.call("cancel_batch", {"batch_id": batch["id"]}, response=True)
        await self.hass.async_block_till_done()
        self.assertEqual(report["status"], "canceled")
        self.assertIn("canceled_at", report)
        self.assertEqual(self.engine.store.data["orders"]["1"]["status"], "canceled")
        self.assertEqual(self.hass.states.get("sensor.prepared_batches").state, "0")
        restored = ReorderStore(self.hass)
        await restored.load()
        self.assertEqual(restored.data["batches"][batch["id"]]["status"], "canceled")
        self.assertEqual(restored.data["orders"]["1"]["status"], "canceled")
        self.assertEqual((await self.call("preview_batch", response=True))["count"], 0)
        self.transport.assert_not_awaited()

    async def test_repeated_cancellation_after_reload_keeps_same_timestamp(self):
        batch = await self.prepare()
        first = await self.call("cancel_batch", {"batch_id": batch["id"]}, response=True)
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertFalse(self.hass.services.has_service("reorder", "cancel_batch"))
        self.assertFalse(self.hass.services.has_service("reorder", "review_batch"))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        second = await self.call("cancel_batch", {"batch_id": batch["id"]}, response=True)
        self.assertEqual(first, second)
        self.transport.assert_not_awaited()

    async def test_cancel_save_failure_restores_original_state(self):
        batch = await self.prepare()
        before = deepcopy(self.engine.store.data)
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.call("cancel_batch", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def test_cancel_notification_failure_is_nonfatal(self):
        batch = await self.prepare()
        with patch("custom_components.reorder.notifications.persistent_notification.async_create", side_effect=RuntimeError("display failed")):
            with self.assertLogs("custom_components.reorder", level="WARNING"):
                await self.call("cancel_batch", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "canceled")
        self.transport.assert_not_awaited()

    async def test_attempted_and_completed_batches_cannot_be_canceled_locally(self):
        batch = await self.prepare()
        await self.submit(batch)
        before = deepcopy(self.engine.store.data)
        with self.assertRaisesRegex(HomeAssistantError, "reconciled with Zinc"):
            await self.call("cancel_batch", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_awaited_once()

    async def test_uncertain_submission_cannot_be_canceled(self):
        batch = await self.prepare()
        self.transport.side_effect = TimeoutError("simulated")
        with self.assertRaises(TimeoutError):
            await self.submit(batch)
        with self.assertRaisesRegex(HomeAssistantError, "reconciled with Zinc"):
            await self.call("cancel_batch", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "submission_unknown")
        self.transport.assert_awaited_once()

    async def test_cancellation_during_submission_cannot_hide_purchase(self):
        batch = await self.prepare()
        entered, release = asyncio.Event(), asyncio.Event()
        async def request(*args):
            entered.set()
            await release.wait()
            return {"id": "mock-zinc-id", "status": "pending"}
        self.transport.side_effect = request
        submission = asyncio.create_task(self.submit(batch))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.assertRaisesRegex(HomeAssistantError, "reconciled with Zinc"):
                await self.call("cancel_batch", {"batch_id": batch["id"]})
        finally:
            release.set()
            await submission
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "pending")
        self.transport.assert_awaited_once()

    async def test_canceled_batch_cannot_submit_or_reappear_on_schedule(self):
        batch = await self.prepare()
        await self.call("cancel_batch", {"batch_id": batch["id"]})
        self.engine.store.data["batch_settings"]["strategy"] = "rolling"
        await self.scheduled(None)
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        with self.assertRaises(HomeAssistantError):
            await self.call("submit_zinc", {"order_id": "1", "confirmation": "SANDBOX"})
        self.assertEqual(len(self.engine.store.data["batches"]), 1)
        self.transport.assert_not_awaited()

    async def test_invalid_batch_membership_blocks_cancellation_and_review(self):
        batch = await self.prepare()
        self.engine.store.data["orders"]["1"]["batch_id"] = "another-batch"
        before = deepcopy(self.engine.store.data)
        for action in ("cancel_batch", "review_batch"):
            with self.assertRaises(HomeAssistantError):
                await self.call(action, {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def select_batch(self, batch):
        await self.hass.async_block_till_done()
        select = self.hass.states.get("select.reorder_batch")
        option = next(label for label in select.attributes["options"] if label.startswith(batch["id"] + " — "))
        await self.hass.services.async_call("select", "select_option", {
            "entity_id": "select.reorder_batch", "option": option,
        }, blocking=True)
        await self.hass.async_block_till_done()

    async def press_batch_button(self, kind):
        await self.hass.services.async_call("button", "press", {
            "entity_id": f"button.reorder_{kind}_batch",
        }, blocking=True)
        await self.hass.async_block_till_done()

    async def test_dashboard_controls_require_an_explicit_batch_selection(self):
        await self.prepare()
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("select.reorder_batch").state, "unknown")
        for kind in ("review", "refresh", "cancel"):
            self.assertEqual(self.hass.states.get(f"button.reorder_{kind}_batch").state, "unavailable")
        self.transport.assert_not_awaited()

    async def test_dashboard_review_and_local_cancel_follow_selection(self):
        batch = await self.prepare()
        await self.select_batch(batch)
        self.assertNotEqual(self.hass.states.get("button.reorder_review_batch").state, "unavailable")
        self.assertNotEqual(self.hass.states.get("button.reorder_cancel_batch").state, "unavailable")
        self.assertEqual(self.hass.states.get("button.reorder_refresh_batch").state, "unavailable")
        await self.press_batch_button("review")
        self.assertEqual(self.hass.data["persistent_notification"][f"reorder_batch_{batch['id']}"]["title"], "Reorder — Batch Review")
        await self.press_batch_button("cancel")
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "canceled")
        self.assertEqual(self.hass.states.get("button.reorder_cancel_batch").state, "unavailable")
        self.assertEqual(self.hass.states.get("select.reorder_batch").state, batch["id"] + " — Canceled")
        self.transport.assert_not_awaited()

    async def test_dashboard_refresh_never_submits_and_updates_selected_label(self):
        batch = await self.prepare()
        await self.submit(batch)
        await self.select_batch(batch)
        self.assertEqual(self.hass.states.get("button.reorder_cancel_batch").state, "unavailable")
        self.transport.reset_mock()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed"}
        await self.press_batch_button("refresh")
        self.transport.assert_awaited_once_with("GET", "/orders/mock-zinc-id")
        self.assertEqual(self.hass.states.get("select.reorder_batch").state, batch["id"] + " — Order placed")

    async def test_dashboard_mode_changes_without_exposing_credentials(self):
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("sensor.reorder_purchasing_mode").state, "Sandbox")
        for options, expected in (
            ({}, "Not configured"),
            ({"zinc_api_key": "not-a-key"}, "Invalid key"),
            ({"zinc_api_key": "zn_live_not-a-real-key"}, "Live disabled"),
            ({"zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True}, "Live enabled"),
        ):
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.hass.async_block_till_done()
            state = self.hass.states.get("sensor.reorder_purchasing_mode")
            self.assertEqual(state.state, expected)
            self.assertNotIn("zinc_api_key", state.attributes)
            self.assertNotIn("not-a-real-key", str(state.attributes))
        self.transport.assert_not_awaited()

    async def test_dashboard_selection_clears_on_reload_without_changing_batches(self):
        batch = await self.prepare()
        await self.select_batch(batch)
        before = deepcopy(self.engine.store.data)
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        self.assertIsNone(self.hass.data["reorder"][self.entry.entry_id].selected_batch_id)
        self.assertEqual(self.hass.states.get("select.reorder_batch").state, "unknown")
        self.assertEqual(self.hass.data["reorder"][self.entry.entry_id].store.data, before)
        self.assertEqual(self.hass.states.get("button.reorder_cancel_batch").state, "unavailable")

    async def test_dashboard_refresh_disables_for_a_different_key_environment(self):
        batch = await self.prepare()
        await self.submit(batch)
        await self.select_batch(batch)
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {
            "zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True,
        })
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get("button.reorder_refresh_batch").state, "unavailable")
        self.transport.assert_awaited_once()

    async def test_dashboard_templates_render_empty_and_populated_batch_lists(self):
        import yaml
        from homeassistant.helpers.template import Template
        dashboard = yaml.safe_load((Path(__file__).resolve().parents[1] / "dashboards/reorder.yaml").read_text())
        cards = [card for section in dashboard["views"][0]["sections"]
                 for card in section["cards"] if card["type"] == "markdown"]
        await self.hass.async_block_till_done()
        empty = "\n".join(str(Template(card["content"], self.hass).async_render()) for card in cards)
        self.assertIn("No prepared batches", empty)
        self.assertEqual(self.hass.states.get("sensor.reorder_purchasing_mode").state, "Sandbox")
        batch = await self.prepare()
        await self.hass.async_block_till_done()
        populated = "\n".join(str(Template(card["content"], self.hass).async_render()) for card in cards)
        self.assertIn(batch["id"], populated)
        self.assertIn("$12.50", populated)
        await self.submit(batch)
        await self.hass.async_block_till_done()
        submitted = "\n".join(str(Template(card["content"], self.hass).async_render()) for card in cards)
        self.assertIn("Submitted", submitted)
        self.assertIn("Sandbox", submitted)

    async def render_batch_contents(self):
        import yaml
        from homeassistant.helpers.template import Template
        dashboard = yaml.safe_load((Path(__file__).resolve().parents[1] / "dashboards/reorder.yaml").read_text())
        card = next(card for section in dashboard["views"][0]["sections"] for card in section["cards"]
                    if card.get("title") == "Batch contents")
        return str(Template(card["content"], self.hass).async_render())

    async def test_selected_contents_appear_inline_without_notification_or_network(self):
        batch = await self.prepare()
        self.engine.store.data["products"]["product 1"] = {"name": "Edited catalog", "quantity": 9}
        before = deepcopy(self.engine.store.data)
        notifications = deepcopy(self.hass.data["persistent_notification"])
        await self.select_batch(batch)
        attributes = self.hass.states.get("select.reorder_batch").attributes
        self.assertEqual(attributes["batch"]["status_label"], "Ready for review")
        self.assertEqual(attributes["orders"][0]["name"], "Product 1")
        self.assertEqual(attributes["orders"][0]["quantity"], 2)
        rendered = await self.render_batch_contents()
        self.assertIn('href="https://example.com/product/1"', rendered)
        self.assertIn("Product 1", rendered)
        self.assertIn("<td>2</td>", rendered)
        self.assertIn("Total ceiling: $12.50", rendered)
        self.assertNotIn("Edited catalog", rendered)
        self.assertEqual(self.engine.store.data, before)
        self.assertEqual(self.hass.data["persistent_notification"], notifications)
        self.transport.assert_not_awaited()

    async def test_inline_review_switches_products_with_batch_selection(self):
        first = await self.prepare()
        self.engine.store.data["orders"]["2"] = order(2)
        second = await self.prepare()
        await self.select_batch(first)
        self.assertIn("Product 1", await self.render_batch_contents())
        await self.select_batch(second)
        rendered = await self.render_batch_contents()
        self.assertIn("Product 2", rendered)
        self.assertNotIn("Product 1", rendered)
        self.transport.assert_not_awaited()

    async def test_inline_review_handles_no_selection_and_missing_order(self):
        await self.hass.async_block_till_done()
        self.assertIn("Choose a batch above", await self.render_batch_contents())
        batch = await self.prepare()
        self.engine.store.data["orders"].pop("1")
        await self.select_batch(batch)
        attributes = self.hass.states.get("select.reorder_batch").attributes
        self.assertIsNone(attributes["batch"])
        self.assertEqual(attributes["orders"], [])
        self.assertIn("incomplete or unavailable", await self.render_batch_contents())
        self.transport.assert_not_awaited()

    async def test_inline_review_includes_batches_older_than_history_window(self):
        oldest = await self.prepare()
        for index in range(2, 28):
            self.engine.store.data["orders"][str(index)] = order(index)
            await self.prepare()
        await self.select_batch(oldest)
        history = self.hass.states.get("sensor.prepared_batches").attributes["batches"]
        self.assertNotIn(oldest["id"], [batch["id"] for batch in history])
        self.assertIn("Product 1", await self.render_batch_contents())
        self.transport.assert_not_awaited()

    async def test_inline_review_escapes_names_and_formats_refresh_time(self):
        self.engine.store.data["orders"]["1"]["name"] = '<script>alert("test")</script> | Coffee'
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.engine.store.data["batches"][batch["id"]]
        saved["last_refreshed_at"] = "2026-11-02T13:55:57.137041+00:00"
        await self.select_batch(batch)
        rendered = await self.render_batch_contents()
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("Nov 02, 2026 at 08:55 AM", rendered)
        self.assertNotIn("2026-11-02T13:55", rendered)
        self.assertIn("Submitted", rendered)

    async def test_sidebar_is_automatically_registered_with_versioned_assets(self):
        from homeassistant.components import frontend
        panel = self.hass.data[frontend.DATA_PANELS]["reorder-app"]
        self.assertEqual(panel.sidebar_title, "Reorder")
        self.assertTrue(panel.require_admin)
        self.assertEqual(panel.config["entry_id"], self.entry.entry_id)
        self.assertEqual(panel.config["_panel_custom"]["module_url"], "/reorder-assets/reorder-panel.js?v=0.9.0")
        self.assertEqual(panel.config["_panel_custom"]["name"], "reorder-panel")

    async def test_sidebar_snapshot_excludes_credentials_and_preserves_data(self):
        import json
        from custom_components.reorder.frontend import panel_data
        batch = await self.prepare()
        before = deepcopy(self.engine.store.data)
        data = panel_data(self.engine, self.entry)
        self.assertEqual(data["mode"], "Sandbox")
        self.assertEqual(data["batches"][0]["id"], batch["id"])
        self.assertEqual(data["batches"][0]["orders"][0]["name"], "Product 1")
        self.assertTrue(data["batches"][0]["can_cancel"])
        self.assertFalse(data["batches"][0]["can_refresh"])
        serialized = json.dumps(data)
        for private in ("zinc_api_key", "shipping_address", "ship_first_name", "zn_test_not-a-real-key", "test-only"):
            self.assertNotIn(private, serialized)
        data["batches"][0]["orders"][0]["quantity"] = 99
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def test_sidebar_websocket_requires_admin_and_loaded_entry(self):
        from types import SimpleNamespace
        from custom_components.reorder.frontend import websocket_panel
        handler = websocket_panel.__wrapped__
        for user in (None, SimpleNamespace(is_admin=False)):
            connection = MagicMock(user=user)
            await handler(self.hass, connection, {"id": 1, "entry_id": self.entry.entry_id})
            connection.send_error.assert_called_once_with(1, "unauthorized", "Administrator access is required")
            connection.send_result.assert_not_called()
        connection = MagicMock(user=SimpleNamespace(is_admin=True))
        await handler(self.hass, connection, {"id": 2, "entry_id": "missing"})
        connection.send_error.assert_called_once_with(2, "not_found", "Reorder is not loaded")
        connection.send_result.assert_not_called()
        self.transport.assert_not_awaited()

    async def test_sidebar_websocket_snapshot_needs_no_zinc_credentials(self):
        from types import SimpleNamespace
        from custom_components.reorder.frontend import websocket_panel
        self.hass.config_entries.async_update_entry(self.entry, options={})
        batch = await self.prepare()
        connection = MagicMock(user=SimpleNamespace(is_admin=True))
        await websocket_panel.__wrapped__(self.hass, connection, {"id": 3, "entry_id": self.entry.entry_id})
        args = connection.send_result.call_args.args
        self.assertEqual(args[0], 3)
        self.assertEqual(args[1]["mode"], "Not configured")
        self.assertEqual(args[1]["batches"][0]["id"], batch["id"])
        self.transport.assert_not_awaited()

    async def test_sidebar_unregisters_and_reregisters_on_reload(self):
        from homeassistant.components import frontend
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertNotIn("reorder-app", self.hass.data[frontend.DATA_PANELS])
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        self.assertIn("reorder-app", self.hass.data[frontend.DATA_PANELS])

    async def test_sidebar_does_not_replace_or_remove_an_unrelated_panel(self):
        from homeassistant.components import frontend
        from custom_components.reorder.frontend import async_setup_panel, async_remove_panel
        frontend.async_register_built_in_panel(self.hass, component_name="config", frontend_url_path="reorder-app", sidebar_title="Existing panel", update=True)
        with self.assertRaisesRegex(ValueError, "will not replace"):
            await async_setup_panel(self.hass, self.entry)
        async_remove_panel(self.hass, self.entry)
        self.assertEqual(self.hass.data[frontend.DATA_PANELS]["reorder-app"].sidebar_title, "Existing panel")

    async def test_sidebar_reflects_refresh_without_allowing_local_cancellation(self):
        from custom_components.reorder.frontend import panel_data
        batch = await self.prepare()
        await self.submit(batch)
        data = panel_data(self.engine, self.entry)
        self.assertTrue(data["batches"][0]["can_refresh"])
        self.assertFalse(data["batches"][0]["can_cancel"])
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {"zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True})
        data = panel_data(self.engine, self.entry)
        self.assertEqual(data["mode"], "Live enabled")
        self.assertFalse(data["batches"][0]["can_refresh"])

    async def test_sidebar_disables_cancel_when_a_member_order_was_attempted(self):
        from custom_components.reorder.frontend import panel_data
        await self.prepare()
        self.engine.store.data["orders"]["1"]["zinc_environment"] = "sandbox"
        self.assertFalse(panel_data(self.engine, self.entry)["batches"][0]["can_cancel"])

    async def configure_coffee(self, **overrides):
        data = {"name": "Coffee", "aliases": ["Morning brew"], "retailer": "zinc",
                "product_id": "https://zinc.com/shop/products/test-success", "quantity": 2,
                "max_price": 25, "cooldown_hours": 168, "enabled": True}
        await self.call("set_product", data | overrides)

    async def setup_shopping_list(self):
        if not self.hass.config_entries.async_entries("shopping_list"):
            result = await self.hass.config_entries.flow.async_init("shopping_list", context={"source": SOURCE_USER}, data={})
            self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()

    async def add_shopping_item(self, name):
        await self.setup_shopping_list()
        await self.hass.services.async_call("shopping_list", "add_item", {"name": name}, blocking=True)
        await self.hass.async_block_till_done()

    def coffee_orders(self):
        return [order for order in self.engine.store.data["orders"].values() if order["product_key"] == "coffee"]

    async def test_real_shopping_list_add_queues_catalog_product(self):
        from custom_components.reorder.frontend import panel_data
        await self.configure_coffee()
        await self.add_shopping_item(" coffee ")
        self.assertTrue(panel_data(self.engine, self.entry)["shopping_list_ready"])
        orders = self.coffee_orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["quantity"], 2)
        self.assertEqual(orders[0]["max_price"], 25)
        self.assertEqual(orders[0]["status"], "queued")
        self.assertIn("Coffee", [order["name"] for order in panel_data(self.engine, self.entry)["queue"]["orders"]])
        self.assertEqual(self.engine.intake_events[0]["reason"], "queued")
        self.transport.assert_not_awaited()

    async def test_builtin_todo_ui_path_queues_matching_alias(self):
        await self.configure_coffee()
        await self.setup_shopping_list()
        await self.hass.services.async_call("todo", "add_item", {"item": "MORNING   BREW"}, target={"entity_id": "todo.shopping_list"}, blocking=True)
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "queued")
        self.transport.assert_not_awaited()

    async def test_repeated_shopping_list_event_does_not_duplicate_queue(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        item = self.hass.data["shopping_list"].items[-1]
        self.hass.bus.async_fire("shopping_list_updated", {"action": "add", "item": item})
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "already_seen")
        self.transport.assert_not_awaited()

    async def test_unmatched_and_disabled_items_have_visible_explanations(self):
        await self.add_shopping_item("coffee")
        self.assertEqual(self.engine.intake_events[0]["reason"], "no_match")
        await self.configure_coffee(enabled=False)
        await self.add_shopping_item("coffee")
        self.assertEqual(self.engine.intake_events[0]["reason"], "disabled")
        self.assertEqual(self.coffee_orders(), [])
        self.transport.assert_not_awaited()

    async def test_ambiguous_catalog_alias_does_not_choose_a_product(self):
        await self.configure_coffee()
        # Legacy stored ambiguity remains diagnosable; new writes now reject it.
        self.engine.store.data["products"]["other coffee"] = deepcopy(self.engine.store.data["products"]["coffee"]) | {"name": "Other coffee", "aliases": ["coffee"]}
        await self.add_shopping_item("coffee")
        self.assertEqual(self.engine.intake_events[0]["reason"], "ambiguous")
        self.assertEqual(self.coffee_orders(), [])
        self.transport.assert_not_awaited()

    async def test_fresh_item_after_local_batch_cancellation_can_queue(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        first = self.coffee_orders()[0]
        batch = await self.prepare()
        await self.call("cancel_batch", {"batch_id": batch["id"]})
        await self.add_shopping_item("coffee")
        self.assertEqual(first["status"], "canceled")
        self.assertEqual(len(self.coffee_orders()), 2)
        self.assertEqual(sum(order["status"] == "queued" for order in self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "queued")
        self.transport.assert_not_awaited()

    async def test_actual_submission_cancellation_still_obeys_cooldown(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        saved.update(status="canceled", zinc_environment="sandbox", zinc_order_id="mock")
        await self.add_shopping_item("coffee")
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "cooldown")
        self.transport.assert_not_awaited()

    async def test_pending_and_uncertain_orders_still_block_new_queue_entries(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        for status in ("pending", "submission_unknown", "order_placed"):
            saved["status"] = status
            await self.add_shopping_item("coffee")
            self.assertEqual(self.engine.intake_events[0]["reason"], "existing_order")
        self.assertEqual(len(self.coffee_orders()), 1)
        self.transport.assert_not_awaited()

    async def test_non_zinc_product_is_explained_as_ineligible_for_zinc_batches(self):
        await self.configure_coffee(retailer="other")
        await self.add_shopping_item("coffee")
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertIn("not eligible for Zinc batches", self.engine.intake_events[0]["message"])
        self.transport.assert_not_awaited()

    async def test_failed_queue_save_rolls_back_seen_item_and_order(self):
        await self.configure_coffee()
        before = deepcopy(self.engine.store.data)
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.engine.match_new_item({"name": "coffee", "id": "fresh-item"})
        self.assertEqual(self.engine.store.data, before)
        self.assertEqual(self.engine.intake_events[0]["reason"], "storage_error")
        await self.engine.match_new_item({"name": "coffee", "id": "fresh-item"})
        self.assertEqual(len(self.coffee_orders()), 1)
        self.transport.assert_not_awaited()

    async def test_intake_activity_is_bounded_and_not_saved_in_order_storage(self):
        from custom_components.reorder.frontend import panel_data
        before = deepcopy(self.engine.store.data)
        for index in range(25):
            await self.engine.match_new_item({"name": f"Unmatched {index}", "id": str(index)})
        self.assertEqual(len(self.engine.intake_events), 20)
        self.assertEqual(self.engine.store.data, before)
        data = panel_data(self.engine, self.entry)
        data["intake_events"].clear()
        self.assertEqual(len(self.engine.intake_events), 20)
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        self.assertEqual(self.hass.data["reorder"][self.entry.entry_id].intake_events, [])

    async def test_sidebar_reports_unconfigured_shopping_list_source(self):
        from custom_components.reorder.frontend import panel_data
        data = panel_data(self.engine, self.entry)
        self.assertFalse(data["shopping_list_ready"])
        self.assertEqual(data["intake_events"], [])
        self.transport.assert_not_awaited()

    async def source_change(self, **changes):
        item = self.hass.data["shopping_list"].items[-1]
        await self.hass.data["shopping_list"].async_update(item["id"], changes)
        await self.hass.async_block_till_done()
        return item

    async def admin_command(self, handler, **values):
        from types import SimpleNamespace
        connection = MagicMock(user=SimpleNamespace(is_admin=True))
        message = handler._ws_schema({"id": 100, "type": handler._ws_command, "entry_id": self.entry.entry_id, **values})
        await handler.__wrapped__(self.hass, connection, message)
        return connection

    async def test_list_rename_replaces_unsubmitted_product_and_deduplicates(self):
        await self.configure_coffee()
        await self.configure_coffee(name="Tea", aliases=[])
        await self.add_shopping_item("coffee")
        first = self.coffee_orders()[0]
        item = await self.source_change(name="Tea")
        self.assertEqual(first["status"], "canceled")
        tea = [order for order in self.engine.store.data["orders"].values() if order["product_key"] == "tea"]
        self.assertEqual(len(tea), 1)
        self.assertEqual(tea[0]["shopping_item_id"], item["id"])
        await self.source_change(name="tea")
        self.assertEqual(len([order for order in self.engine.store.data["orders"].values() if order["product_key"] == "tea"]), 1)
        self.transport.assert_not_awaited()

    async def test_alias_rename_keeps_ready_batch_and_frozen_product_values(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        saved = self.coffee_orders()[0]
        before = {key: saved[key] for key in ("product_id", "quantity", "max_price", "batch_id")}
        await self.source_change(name="Morning brew")
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "ready")
        self.assertEqual({key: saved[key] for key in before}, before)
        self.assertEqual(saved["shopping_item_name"], "Morning brew")
        self.transport.assert_not_awaited()

    async def test_unmatched_rename_invalidates_batch_and_preserves_history(self):
        from custom_components.reorder.frontend import panel_data
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()  # Includes the unrelated fixture product too.
        await self.source_change(name="Unapproved snacks")
        stored = self.engine.store.data["batches"][batch["id"]]
        self.assertEqual(stored["status"], "invalidated")
        self.assertEqual(self.coffee_orders()[0]["status"], "canceled")
        self.assertEqual(self.engine.store.data["orders"]["1"]["status"], "queued")
        self.assertNotIn("batch_id", self.engine.store.data["orders"]["1"])
        report = await self.call("review_batch", {"batch_id": batch["id"]}, response=True)
        self.assertEqual({line["status"] for line in report["orders"]}, {"canceled", "returned_to_queue"})
        self.assertIsNone(panel_data(self.engine, self.entry)["batches"][0]["review_error"])
        await self.prepare()  # Reassign the survivor; the old audit view must still work.
        self.assertEqual((await self.call("review_batch", {"batch_id": batch["id"]}, response=True))["orders"], report["orders"])
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_completion_and_unchecking_queue_exactly_one_new_order(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        first = self.coffee_orders()[0]
        await self.source_change(complete=True)
        self.assertEqual(first["status"], "canceled")
        await self.source_change(complete=False)
        await self.source_change(complete=False)
        self.assertEqual(len(self.coffee_orders()), 2)
        self.assertEqual(sum(order["status"] == "queued" for order in self.coffee_orders()), 1)
        self.transport.assert_not_awaited()

    async def test_remove_invalidates_ready_batch_and_returns_other_lines(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        item = self.hass.data["shopping_list"].items[-1]
        await self.hass.data["shopping_list"].async_remove(item["id"])
        await self.hass.async_block_till_done()
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "invalidated")
        self.assertEqual(self.coffee_orders()[0]["status"], "canceled")
        self.assertEqual(self.engine.store.data["orders"]["1"]["status"], "queued")
        self.assertNotIn("batch_id", self.engine.store.data["orders"]["1"])
        self.transport.assert_not_awaited()

    async def test_submitted_item_rename_completion_and_removal_never_cancel_purchase(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        await self.call("submit_zinc", {"order_id": saved["id"], "confirmation": "SANDBOX"})
        before = deepcopy(saved)
        await self.source_change(name="Tea")
        await self.source_change(complete=True)
        item = self.hass.data["shopping_list"].items[-1]
        await self.hass.data["shopping_list"].async_remove(item["id"])
        await self.hass.async_block_till_done()
        self.assertEqual(saved, before)
        self.assertEqual(self.engine.intake_events[0]["reason"], "submitted_unchanged")
        self.transport.assert_awaited_once()

    async def test_unknown_submission_is_untouched_by_list_removal(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        self.transport.side_effect = TimeoutError("simulated")
        with self.assertRaises(TimeoutError):
            await self.call("submit_zinc", {"order_id": saved["id"], "confirmation": "SANDBOX"})
        item = self.hass.data["shopping_list"].items[-1]
        await self.hass.data["shopping_list"].async_remove(item["id"])
        await self.hass.async_block_till_done()
        self.assertEqual(saved["status"], "submission_unknown")
        self.assertEqual(self.engine.intake_events[0]["reason"], "submitted_unchanged")
        self.transport.assert_awaited_once()

    async def test_bulk_complete_clear_and_uncheck_do_not_duplicate_or_purchase(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        await self.hass.data["shopping_list"].async_update_list({"complete": True})
        await self.hass.async_block_till_done()
        self.assertEqual(self.coffee_orders()[0]["status"], "canceled")
        await self.hass.data["shopping_list"].async_update_list({"complete": False})
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.coffee_orders()), 2)
        await self.hass.data["shopping_list"].async_update_list({"complete": True})
        await self.hass.data["shopping_list"].async_clear_completed()
        await self.hass.async_block_till_done()
        self.assertTrue(all(order["status"] == "canceled" for order in self.coffee_orders()))
        self.assertEqual(self.engine.store.data["orders"]["1"]["status"], "queued")
        self.transport.assert_not_awaited()

    async def test_list_sync_off_and_unavailable_source_never_guess_cancellation(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        before = deepcopy(self.engine.store.data)
        await self.engine.handle_shopping_event("clear", items=None)
        self.assertEqual(self.engine.store.data, before)
        self.engine.store.data["preferences"]["sync_shopping_list"] = False
        await self.source_change(complete=True)
        self.assertEqual(self.coffee_orders()[0]["status"], "queued")
        self.assertEqual(self.engine.intake_events[0]["reason"], "sync_disabled")
        self.transport.assert_not_awaited()

    async def test_manual_cancel_is_not_undone_by_unchecking_an_item(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        await self.source_change(complete=True)
        await self.source_change(complete=False)
        batch = await self.prepare()
        await self.call("cancel_batch", {"batch_id": batch["id"]})
        await self.source_change(complete=False)
        self.assertEqual(len(self.coffee_orders()), 2)
        self.assertTrue(all(order["status"] == "canceled" for order in self.coffee_orders()))
        self.transport.assert_not_awaited()

    async def test_sync_save_failure_restores_batch_orders_and_links(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        await self.prepare()
        before = deepcopy(self.engine.store.data)
        item = deepcopy(self.hass.data["shopping_list"].items[-1])
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.engine.handle_shopping_event("remove", item)
        self.assertEqual(self.engine.store.data, before)
        self.assertEqual(self.engine.intake_events[0]["reason"], "storage_error")
        self.transport.assert_not_awaited()

    async def test_submission_rechecks_list_before_a_remove_event_is_processed(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        self.hass.data["shopping_list"].items.clear()  # Source state changed; event is pending.
        before = deepcopy(self.engine.store.data)
        with self.assertRaisesRegex(HomeAssistantError, "removed or completed"):
            await self.submit(batch)
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def test_rapid_rename_then_complete_cannot_resurrect_an_order(self):
        await self.configure_coffee()
        await self.configure_coffee(name="Tea", aliases=[])
        await self.add_shopping_item("coffee")
        item = self.hass.data["shopping_list"].items[-1]
        await asyncio.gather(self.hass.data["shopping_list"].async_update(item["id"], {"name": "Tea"}),
                             self.hass.data["shopping_list"].async_update(item["id"], {"complete": True}))
        await self.hass.async_block_till_done()
        self.assertTrue(all(order["status"] == "canceled" for order in self.engine.store.data["orders"].values()
                            if order.get("shopping_item_id") == item["id"]))
        self.transport.assert_not_awaited()

    async def test_product_management_ws_validates_and_keeps_order_snapshots(self):
        from custom_components.reorder.frontend import websocket_product_save, websocket_product_remove, panel_data
        product = {"name": "Coffee", "retailer": "zinc", "product_id": "https://example.com/coffee", "aliases": ["brew"]}
        result = await self.admin_command(websocket_product_save, product=product)
        result.send_result.assert_called_once_with(100, {"saved": True})
        await self.add_shopping_item("Coffee")
        saved = deepcopy(self.coffee_orders()[0])
        result = await self.admin_command(websocket_product_save, product=product | {"quantity": 3, "max_price": 30}, original_name="Coffee")
        result.send_error.assert_not_called()
        self.assertEqual(self.coffee_orders()[0], saved)
        self.assertFalse(panel_data(self.engine, self.entry)["catalog"][0]["can_rename"])
        result = await self.admin_command(websocket_product_save, product=product | {"name": "New name"}, original_name="Coffee")
        result.send_error.assert_called_once()
        await self.admin_command(websocket_product_remove, name="Coffee")
        self.assertNotIn("coffee", self.engine.store.data["products"])
        self.assertEqual(self.coffee_orders()[0], saved)
        self.transport.assert_not_awaited()

    async def test_product_creation_conflicts_and_invalid_url_do_not_overwrite(self):
        from custom_components.reorder.frontend import websocket_product_save
        await self.configure_coffee()
        before = deepcopy(self.engine.store.data)
        for product in (
            {"name": "Coffee", "retailer": "zinc", "product_id": "https://example.com/new"},
            {"name": "Tea", "aliases": ["coffee"], "retailer": "zinc", "product_id": "https://example.com/tea"},
            {"name": "Tea", "retailer": "zinc", "product_id": "http://example.com/tea"},
        ):
            connection = await self.admin_command(websocket_product_save, product=product)
            connection.send_error.assert_called_once()
            self.assertEqual(self.engine.store.data, before)

    async def test_product_and_preference_save_failures_restore_config(self):
        await self.configure_coffee()
        before = deepcopy(self.engine.store.data)
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.engine.remove_product("coffee")
            self.assertEqual(self.engine.store.data, before)
            with self.assertRaises(OSError):
                await self.engine.upsert_product("Coffee", [], "zinc", "https://example.com/new", 3, 25, 24, True)
            self.assertEqual(self.engine.store.data, before)
            with self.assertRaises(OSError):
                await self.engine.update_preferences(strategy="weekly", weekday=1, hour=12, rolling_hours=24)
            self.assertEqual(self.engine.store.data, before)

    async def test_preference_save_preserves_credentials_and_same_schedule_date(self):
        from custom_components.reorder.frontend import websocket_preferences_save
        self.engine.store.data["batch_settings"]["last_scheduled_date"] = "2026-11-02"
        before_options = dict(self.entry.options)
        connection = await self.admin_command(websocket_preferences_save, preferences={"strategy": "manual", "weekday": 6, "hour": 10, "rolling_hours": 48, "sync_shopping_list": False})
        connection.send_error.assert_not_called()
        self.assertEqual(self.engine.store.data["batch_settings"]["last_scheduled_date"], "2026-11-02")
        self.assertFalse(self.engine.store.data["preferences"]["sync_shopping_list"])
        self.assertEqual(dict(self.entry.options), before_options)

    async def test_management_commands_reject_non_admin_users(self):
        from types import SimpleNamespace
        from custom_components.reorder.frontend import websocket_product_save, websocket_product_remove, websocket_preferences_save, websocket_sandbox_submit, websocket_receive_items, websocket_notification_test, websocket_notifications_save
        before = deepcopy(self.engine.store.data)
        for handler in (websocket_product_save, websocket_product_remove, websocket_preferences_save, websocket_sandbox_submit, websocket_receive_items, websocket_notification_test, websocket_notifications_save):
            connection = MagicMock(user=SimpleNamespace(is_admin=False))
            await handler.__wrapped__(self.hass, connection, {"id": 1, "entry_id": self.entry.entry_id})
            connection.send_error.assert_called_once_with(1, "unauthorized", "Administrator access is required")
        self.assertEqual(self.engine.store.data, before)

    async def test_legacy_options_product_save_preserves_zinc_options(self):
        before = dict(self.entry.options)
        result = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_product"})
        self.assertEqual(result["step_id"], "add_product")
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], {
            "name": "Tea", "aliases": "tea", "retailer": "zinc", "product_id": "https://example.com/tea",
            "quantity": 1, "max_price": 25, "cooldown_hours": 168, "enabled": True,
            "substitute_1": "", "substitute_2": "",
        })
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(dict(self.entry.options), before)
        self.assertIn("tea", self.engine.store.data["products"])

    async def test_disabling_catalog_does_not_cancel_an_unchanged_queued_snapshot(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        await self.configure_coffee(enabled=False)
        await self.source_change(complete=False)
        self.assertEqual(saved["status"], "queued")
        self.assertEqual(self.engine.intake_events[0]["reason"], "unchanged")
        self.transport.assert_not_awaited()

    async def test_reorder_list_event_does_not_change_orders(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        before = deepcopy(self.engine.store.data)
        self.hass.data["shopping_list"].async_reorder([item["id"] for item in self.hass.data["shopping_list"].items])
        await self.hass.async_block_till_done()
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()

    async def test_legacy_schedule_options_save_preserves_zinc_credentials(self):
        before = dict(self.entry.options)
        result = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "batch_settings"})
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], {
            "strategy": "weekly", "weekday": 1, "hour": 12, "rolling_hours": 24,
        })
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(dict(self.entry.options), before)
        self.assertEqual(self.engine.store.data["batch_settings"]["strategy"], "weekly")

    async def test_pending_ambiguous_alias_edit_blocks_stale_submission(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        self.engine.store.data["products"]["legacy tea"] = deepcopy(self.engine.store.data["products"]["coffee"]) | {"name": "Legacy tea", "aliases": ["morning brew"]}
        self.hass.data["shopping_list"].items[-1]["name"] = "Morning brew"
        with self.assertRaisesRegex(HomeAssistantError, "renamed"):
            await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_removal_during_submission_does_not_cancel_inflight_work(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        entered, release = asyncio.Event(), asyncio.Event()
        async def request(*args):
            entered.set()
            await release.wait()
            return {"id": "mock-zinc-id", "status": "pending"}
        self.transport.side_effect = request
        submission = asyncio.create_task(self.submit(batch))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            item = self.hass.data["shopping_list"].items[-1]
            await self.hass.data["shopping_list"].async_remove(item["id"])
            await asyncio.sleep(0)
        finally:
            release.set()
            await submission
        await self.hass.async_block_till_done()
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "pending")
        self.assertEqual(self.coffee_orders()[0]["status"], "pending")
        self.assertEqual(self.engine.intake_events[0]["reason"], "submitted_unchanged")
        self.transport.assert_awaited_once()

    def provider_item(self, order, status="ordered", error=None):
        return {"id": "provider-" + order["id"], "url": order["product_id"],
                "quantity": order["quantity"], "status": status, "error_type": error}

    async def test_app_submission_is_sandbox_only_and_reuses_native_guards(self):
        from custom_components.reorder.frontend import websocket_sandbox_submit
        batch = await self.prepare()
        before = deepcopy(self.engine.store.data)
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {"zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True})
        connection = await self.admin_command(websocket_sandbox_submit, batch_id=batch["id"], confirmation="SANDBOX")
        connection.send_error.assert_called_once()
        self.assertEqual(self.engine.store.data, before)
        self.transport.assert_not_awaited()
        self.hass.config_entries.async_update_entry(self.entry, options=self.options)
        connection = await self.admin_command(websocket_sandbox_submit, batch_id=batch["id"], confirmation="SANDBOX")
        connection.send_error.assert_not_called()
        self.transport.assert_awaited_once()
        with self.assertRaises(HomeAssistantError):
            await self.admin_command(websocket_sandbox_submit, batch_id=batch["id"], confirmation="SANDBOX")
        self.transport.assert_awaited_once()

    async def test_refresh_exposes_sanitized_tracking_cost_and_item_failure(self):
        import json
        from custom_components.reorder.frontend import panel_data
        batch = await self.prepare()
        await self.submit(batch)
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_failed",
            "items": [self.provider_item(self.engine.store.data["orders"]["1"], "failed", "product_out_of_stock")],
            "tracking_numbers": [{"carrier": "usps", "tracking_number": "TEST123", "status": "in_transit", "zinc_tracking_url": "https://www.17track.net/test", "estimated_delivery_date": "2026-11-06", "delivery_proof_url": "https://example.com/private-address-photo"}],
            "job_result": {"error_type": "product_out_of_stock", "error": "Private address and API key must not be retained", "price_components": {"total": 1234, "tax": 100}, "shipping_address": {"first_name": "private"}},
            "shipping_address": {"first_name": "private"}, "api_key": "zn_test_private"}
        report = await self.call("refresh_batch_zinc", {"batch_id": batch["id"]}, response=True)
        details = report["fulfillment"]
        self.assertEqual(details["error_code"], "product_out_of_stock")
        self.assertEqual(details["prices_cents"]["total"], 1234)
        self.assertEqual(details["shipments"][0]["tracking_number"], "TEST123")
        self.assertEqual(details["items"][0]["status"], "failed")
        serialized = json.dumps(panel_data(self.engine, self.entry))
        for private in ("private-address-photo", "shipping_address", "zn_test_private", "Private address"):
            self.assertNotIn(private, serialized)
        self.assertEqual(report["status"], "order_failed")

    async def test_order_placed_alone_never_updates_the_shopping_list(self):
        from custom_components.reorder.frontend import panel_data
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed"}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(panel_data(self.engine, self.entry)["batches"][0]["receivable_order_ids"], [])

    async def test_explicit_sandbox_receipt_completes_only_the_selected_uuid(self):
        from custom_components.reorder.frontend import websocket_receive_items
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        first_item = self.hass.data["shopping_list"].items[-1]
        await self.add_shopping_item("coffee")  # Same name, distinct source ID; not linked to an order.
        other_item = self.hass.data["shopping_list"].items[-1]
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        count = self.transport.await_count
        result = await self.admin_command(websocket_receive_items, batch_id=batch["id"], order_ids=[saved["id"]], confirmation="SIMULATE RECEIPT")
        await self.hass.async_block_till_done()
        self.assertTrue(first_item["complete"])
        self.assertFalse(other_item["complete"])
        self.assertEqual(result.send_result.call_args.args[1]["results"][0]["status"], "completed")
        self.assertEqual(saved["status"], "order_placed")
        self.assertEqual(self.transport.await_count, count)  # List update made no Zinc request.
        result = await self.admin_command(websocket_receive_items, batch_id=batch["id"], order_ids=[saved["id"]], confirmation="SIMULATE RECEIPT")
        self.assertEqual(result.send_result.call_args.args[1]["results"][0]["status"], "already_complete")

    async def test_partial_failure_does_not_complete_failed_or_skipped_items(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        await self.configure_coffee(name="Tea", aliases=[], product_id="https://zinc.com/shop/products/test-out-of-stock")
        await self.add_shopping_item("Tea")
        batch = await self.prepare()
        await self.submit(batch)
        coffee = self.coffee_orders()[0]
        tea = next(order for order in self.engine.store.data["orders"].values() if order["product_key"] == "tea")
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(coffee), self.provider_item(tea, "skipped", "product_out_of_stock")]}
        report = await self.call("refresh_batch_zinc", {"batch_id": batch["id"]}, response=True)
        self.assertEqual(report["fulfillment"]["outcome"], "partial")
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            await self.engine.complete_received_items(batch["id"], [coffee["id"], tea["id"]], True)
        self.assertTrue(all(not item["complete"] for item in self.hass.data["shopping_list"].items))
        await self.engine.complete_received_items(batch["id"], [coffee["id"]], True)
        self.assertTrue(self.hass.data["shopping_list"].items[0]["complete"])
        self.assertFalse(self.hass.data["shopping_list"].items[1]["complete"])

    async def test_receipt_skips_renamed_or_removed_items(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        await self.source_change(name="Unrelated new request")
        report = await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertEqual(report["results"][0]["status"], "skipped_renamed")
        item = self.hass.data["shopping_list"].items[-1]
        self.assertFalse(item["complete"])
        await self.hass.data["shopping_list"].async_remove(item["id"])
        await self.hass.async_block_till_done()
        report = await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertEqual(report["results"][0]["status"], "skipped_missing")

    async def test_live_receipt_requires_explicit_item_delivery_not_tracking_alone(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        stored = self.engine.store.data["batches"][batch["id"]]
        stored["zinc_environment"] = "live"  # Synthetic stored state; no live request is made.
        saved["zinc_environment"] = "live"
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved, "ordered")], "tracking_numbers": [{"status": "delivered"}]}
        from custom_components.reorder.fulfillment import fulfillment_snapshot
        stored["status"] = "order_placed"
        stored["fulfillment"] = fulfillment_snapshot(self.transport.return_value)
        with self.assertRaises(ValueError):
            await self.engine.complete_received_items(batch["id"], [saved["id"]], False)
        stored["fulfillment"]["items"][0]["status"] = "delivered"
        await self.engine.complete_received_items(batch["id"], [saved["id"]], False)
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        self.transport.assert_awaited_once()  # Only the original mocked sandbox submission.

    async def test_receipt_metadata_failure_is_retryable_without_another_purchase(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ValueError, "may already be complete"):
                await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        report = await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertEqual(report["results"][0]["status"], "already_complete")
        self.assertEqual(self.transport.await_count, 2)

    async def test_malformed_fulfillment_refresh_keeps_saved_status_and_details(self):
        batch = await self.prepare()
        await self.submit(batch)
        before = deepcopy(self.engine.store.data)
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": "invalid"}
        with self.assertRaises(HomeAssistantError):
            await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.assertEqual(self.engine.store.data, before)

    async def test_successful_receipt_keeps_cooldown_but_allows_future_reorder(self):
        from datetime import timedelta
        from homeassistant.util import dt as dt_util
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        anchor = saved["shopping_list_completed_at"]
        await self.add_shopping_item("coffee")
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "cooldown")
        await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertEqual(saved["shopping_list_completed_at"], anchor)
        future = dt_util.utcnow() + timedelta(days=8)
        with patch("custom_components.reorder.core.dt_util.utcnow", return_value=future):
            await self.engine.match_new_item({"name": "coffee", "id": "fresh-future-item"})
        self.assertEqual(len(self.coffee_orders()), 2)
        self.assertEqual(sum(order["status"] == "queued" for order in self.coffee_orders()), 1)
        self.assertEqual(self.transport.await_count, 2)

    async def test_unknown_response_with_known_id_can_be_reconciled_by_refresh(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "pending", "items": "malformed"}
        with self.assertRaises(HomeAssistantError):
            await self.submit(batch)
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "submission_unknown")
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.assertEqual(saved["zinc_order_id"], "mock-zinc-id")
        await self.engine.complete_received_items(batch["id"], [saved["id"]], True)
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(self.transport.await_count, 2)

    async def test_receipt_confirmation_and_mode_mismatch_cannot_update_list(self):
        from custom_components.reorder.frontend import websocket_receive_items
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved)]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        result = await self.admin_command(websocket_receive_items, batch_id=batch["id"], order_ids=[saved["id"]], confirmation="ITEMS RECEIVED")
        result.send_error.assert_called_once()
        self.hass.config_entries.async_update_entry(self.entry, options=self.options | {"zinc_api_key": "zn_live_not-a-real-key", "zinc_live_enabled": True})
        result = await self.admin_command(websocket_receive_items, batch_id=batch["id"], order_ids=[saved["id"]], confirmation="ITEMS RECEIVED")
        result.send_error.assert_called_once()
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(self.transport.await_count, 2)

    async def test_provider_delivery_completes_list_and_starts_repeat_cooldown(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [self.provider_item(saved, "delivered")]}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        self.assertIn("delivery_confirmed_at", saved)
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        await self.add_shopping_item("coffee")
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.intake_events[0]["reason"], "cooldown")
        self.assertEqual(self.transport.await_count, 2)

    async def delivered_coffee(self):
        self.engine.store.data["orders"].clear()
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        await self.submit(batch)
        saved = self.coffee_orders()[0]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed",
            "items": [self.provider_item(saved, "delivered")]}
        return batch, saved

    async def test_auto_delivery_completes_once_and_does_not_reclear_unchecked_item(self):
        batch, saved = await self.delivered_coffee()
        with patch.object(type(self.hass.services), "async_call", wraps=self.hass.services.async_call) as calls:
            await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
            await self.hass.async_block_till_done()
            first = saved["shopping_list_completed_at"]
            await self.source_change(complete=False)
            await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
            updates = [call for call in calls.await_args_list if call.args[:2] == ("todo", "update_item")]
            self.assertEqual(len(updates), 1)
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(saved["shopping_list_completed_at"], first)
        self.assertEqual(saved["status"], "order_placed")

    async def test_auto_delivery_does_not_complete_replacement_uuid_or_renamed_source(self):
        batch, saved = await self.delivered_coffee()
        original = self.hass.data["shopping_list"].items[-1]
        await self.hass.data["shopping_list"].async_remove(original["id"])
        await self.add_shopping_item("coffee")
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["receipt_results"][saved["id"]]["status"], "skipped_missing")

    async def test_auto_delivery_failure_preserves_delivery_and_retries_list_only(self):
        batch, saved = await self.delivered_coffee()
        original = self.hass.services.async_call
        async def fail_list(domain, service, *args, **kwargs):
            if domain == "todo":
                raise HomeAssistantError("synthetic failure")
            return await original(domain, service, *args, **kwargs)
        with patch.object(type(self.hass.services), "async_call", side_effect=fail_list):
            report = await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertEqual(report["status"], "order_placed")
        self.assertTrue(report["list_sync_error"])
        self.assertIn("delivery_confirmed_at", saved)
        report = await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(report["list_sync_error"])
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertTrue(all(call.args[0] == "GET" for call in self.transport.await_args_list[1:]))

    async def test_delivery_automation_can_be_disabled_without_disabling_tracking(self):
        batch, saved = await self.delivered_coffee()
        await self.engine.update_preferences(strategy="manual", weekday=6, hour=10,
            rolling_hours=48, auto_complete_delivered=False)
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertIn("delivery_confirmed_at", saved)
        # Older clients omitting the new preference preserve its saved value.
        await self.engine.update_preferences(strategy="manual", weekday=6, hour=10, rolling_hours=48)
        self.assertFalse(self.engine.store.data["preferences"]["auto_complete_delivered"])

    async def test_periodic_tracking_get_only_and_completed_batches_stop_polling(self):
        batch, saved = await self.delivered_coffee()
        # Read-only tracking works without purchasing enablement or address fields.
        self.hass.config_entries.async_update_entry(self.entry, options={"zinc_api_key": "zn_test_not-a-real-key"})
        await self.scheduled(None)
        await self.hass.async_block_till_done()
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        count = self.transport.await_count
        await self.scheduled(None)
        self.assertEqual(self.transport.await_count, count)
        self.assertEqual(self.transport.await_args_list[-1].args[0], "GET")

    async def test_reconciliation_recovers_missed_add_remove_and_completion_events(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        batch = await self.prepare()
        # Simulate deletion while Reorder was offline: no source event is emitted.
        self.hass.data["shopping_list"].items.clear()
        await self.engine.reconcile_shopping_list()
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "invalidated")
        self.hass.data["shopping_list"].items.append({"id": "offline-add", "name": "coffee", "complete": False})
        await self.engine.reconcile_shopping_list()
        await self.engine.reconcile_shopping_list()
        self.assertEqual(sum(order["status"] == "queued" for order in self.coffee_orders()), 1)
        self.assertEqual(self.coffee_orders()[-1]["shopping_item_id"], "offline-add")
        self.transport.assert_not_awaited()

    async def test_poll_failure_is_visible_and_later_refresh_clears_it(self):
        batch, saved = await self.delivered_coffee()
        response = self.transport.return_value
        self.transport.side_effect = TimeoutError("private provider payload")
        with self.assertLogs("custom_components.reorder", level="WARNING"):
            await self.engine.refresh_pending_batches(ZincClient(None, "zn_test_fake"), "sandbox")
        self.assertTrue(self.engine.store.data["batches"][batch["id"]]["refresh_error"])
        self.assertEqual(saved["status"], "submitted")
        self.transport.side_effect = None
        self.transport.return_value = response
        await self.engine.refresh_pending_batches(ZincClient(None, "zn_test_fake"), "sandbox")
        self.assertNotIn("refresh_error", self.engine.store.data["batches"][batch["id"]])
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])

    async def test_delivered_partial_batch_completes_only_delivered_lines(self):
        batch, coffee = await self.delivered_coffee()
        await self.configure_coffee(name="Tea", aliases=[], product_id="https://zinc.com/shop/products/test-out-of-stock")
        await self.add_shopping_item("Tea")
        tea = next(order for order in self.engine.store.data["orders"].values() if order["product_key"] == "tea")
        # Synthetic provider membership; no additional submission.
        stored = self.engine.store.data["batches"][batch["id"]]
        stored["order_ids"].append(tea["id"])
        tea.update(batch_id=batch["id"], zinc_environment="sandbox", zinc_order_id="mock-zinc-id", status="submitted")
        self.transport.return_value["items"].append(self.provider_item(tea, "failed", "product_out_of_stock"))
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertTrue(self.hass.data["shopping_list"].items[0]["complete"])
        self.assertFalse(self.hass.data["shopping_list"].items[1]["complete"])
        self.assertEqual(stored["fulfillment"]["outcome"], "partial")

    async def test_auto_delivery_metadata_failure_keeps_provider_state_and_recovers(self):
        batch, saved = await self.delivered_coffee()
        with patch.object(self.engine.store, "save", side_effect=[None, OSError("disk full"), None]):
            with self.assertLogs("custom_components.reorder", level="WARNING"):
                report = await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertEqual(report["status"], "order_placed")
        self.assertTrue(report["list_sync_error"])
        self.assertNotIn("shopping_list_completed_at", saved)
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertIn("shopping_list_completed_at", saved)
        self.assertFalse(self.engine.store.data["batches"][batch["id"]]["list_sync_error"])

    async def test_delivery_completion_survives_reload_and_does_not_reclear(self):
        batch, saved = await self.delivered_coffee()
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        await self.hass.async_block_till_done()
        anchor = saved["shopping_list_completed_at"]
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        self.engine = self.hass.data["reorder"][self.entry.entry_id]
        await self.source_change(complete=False)
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertEqual(self.coffee_orders()[0]["shopping_list_completed_at"], anchor)

    async def test_auto_delivery_skips_changed_name_and_ambiguous_mapping(self):
        batch, saved = await self.delivered_coffee()
        await self.source_change(name="Different request")
        report = await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertEqual(report["receipt_results"][saved["id"]]["status"], "skipped_renamed")
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        await self.source_change(name="coffee")
        self.transport.return_value["items"].append(deepcopy(self.transport.return_value["items"][0]))
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])

    async def test_polling_is_bounded_fair_and_never_submits(self):
        batches = {}
        for index in range(12):
            batches[str(index)] = {"id": str(index), "order_ids": ["1"], "status": "pending",
                "zinc_order_id": "provider-" + str(index), "zinc_environment": "sandbox"}
        self.engine.store.data["batches"] = batches
        client = MagicMock()
        with patch.object(self.engine, "refresh_batch_zinc", AsyncMock()) as refresh:
            await self.engine.refresh_pending_batches(client, "live")
            refresh.assert_not_awaited()
            await self.engine.refresh_pending_batches(client, "sandbox")
            self.assertEqual(refresh.await_count, 10)
            await self.engine.refresh_pending_batches(client, "sandbox")
            self.assertEqual(refresh.await_count, 20)
            self.assertEqual(len({call.args[0] for call in refresh.await_args_list}), 12)
        self.transport.assert_not_awaited()

    async def test_exact_split_package_delivery_completes_only_after_all_packages_arrive(self):
        batch, saved = await self.delivered_coffee()
        item = self.provider_item(saved, "ordered") | {"tracking_number_ids": ["package-1", "package-2"]}
        packages = [{"id": "package-1", "status": "delivered", "order_item_ids": [item["id"]], "item_mapping": "exact"},
                    {"id": "package-2", "status": "in_transit", "order_item_ids": [item["id"]], "item_mapping": "exact"}]
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed", "items": [item], "tracking_numbers": packages}
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertNotIn("delivery_confirmed_at", saved)
        packages[1]["status"] = "delivered"
        packages[1]["item_mapping"] = "inferred"
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertFalse(self.hass.data["shopping_list"].items[-1]["complete"])
        packages[1]["item_mapping"] = "exact"
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        self.assertIn("delivery_confirmed_at", saved)
        from custom_components.reorder.frontend import panel_data
        self.assertTrue(panel_data(self.engine, self.entry)["batches"][0]["orders"][0]["delivery_confirmed"])
        count = self.transport.await_count
        await self.engine.refresh_pending_batches(ZincClient(None, "zn_test_fake"), "sandbox")
        self.assertEqual(count, self.transport.await_count)

    async def configure_notification_destinations(self, events=None, failure=False):
        import voluptuous as vol
        self.notification_calls = []
        async def record(call):
            self.notification_calls.append((call.domain, call.service, dict(call.data)))
            if failure:
                raise HomeAssistantError("synthetic destination failure")
        self.hass.services.async_register("notify", "test_phone", record,
            schema=vol.Schema({vol.Required("message"): str, vol.Optional("title"): str}))
        self.hass.services.async_register("notify", "send_message", record,
            schema=vol.Schema({vol.Required("message"): str, vol.Optional("entity_id"): vol.Any(str, [str])}))
        self.hass.services.async_register("esphome", "kitchen_tablet_notification", record,
            schema=vol.Schema({vol.Required("message"): str, vol.Required("title"): str,
                vol.Required("duration"): int, vol.Required("type"): str, vol.Required("chime"): bool,
                vol.Required("scale"): float, vol.Required("icon"): str, vol.Required("chime_file"): str,
                vol.Required("volume"): int, vol.Required("image"): str}))
        self.hass.states.async_set("notify.test_display", "unknown", {"friendly_name": "Test display"})
        await self.engine.update_notifications({"persistent": False,
            "events": events if events is not None else ["cart_added", "batch_ready", "order_status", "delivery", "attention", "list_change"],
            "notify_services": ["notify.test_phone"], "notify_entities": ["notify.test_display"],
            "kiosk_services": ["esphome.kitchen_tablet_notification"], "kiosk_duration": 45,
            "kiosk_chime": False, "kiosk_scale": 1.5})

    async def test_notifications_cart_and_ready_route_once_after_saved_state(self):
        await self.configure_notification_destinations()
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        self.assertEqual(len(self.notification_calls), 3)
        for _, _, data in self.notification_calls:
            self.assertIn("Added Coffee", data["message"])
            self.assertIn("No purchase", data["message"])
        batch = await self.prepare()
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 6)
        self.assertIn(batch["id"], self.engine.store.data["batches"])
        self.assertTrue(all("Nothing has been purchased" in data["message"] for _, _, data in self.notification_calls[3:]))
        item = self.hass.data["shopping_list"].items[-1]
        await self.engine.handle_shopping_event("add", item)
        with self.assertRaises(HomeAssistantError):
            await self.prepare()
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 6)
        self.transport.assert_not_awaited()

    async def test_kiosk_payload_uses_documented_action_and_configured_options(self):
        from custom_components.reorder.notifications import async_deliver
        await self.configure_notification_destinations()
        result = await async_deliver(self.engine, "batch_ready", "Review the saved batch.", batch_id="example")
        self.assertEqual(result, {"sent": 3, "failed": 0})
        _, service, data = self.notification_calls[-1]
        self.assertEqual(service, "kitchen_tablet_notification")
        self.assertEqual(data["duration"], 45)
        self.assertFalse(data["chime"])
        self.assertEqual(data["scale"], 1.5)
        self.assertEqual(data["type"], "warning")
        self.assertEqual(data["image"], "")
        self.assertNotIn("confirmation", data)
        self.transport.assert_not_awaited()

    async def test_notify_entity_uses_title_free_supported_message_api(self):
        from custom_components.reorder.notifications import async_deliver
        await self.configure_notification_destinations()
        await async_deliver(self.engine, "cart_added", "Saved locally.")
        data = self.notification_calls[1][2]
        self.assertEqual(data["entity_id"], "notify.test_display")
        self.assertNotIn("title", data)
        self.assertIn("Reorder", data["message"])

    async def test_notification_failures_do_not_change_cart_or_batch_results(self):
        await self.configure_notification_destinations(failure=True)
        await self.configure_coffee()
        with self.assertLogs("custom_components.reorder", level="WARNING"):
            await self.add_shopping_item("coffee")
            batch = await self.prepare()
            await self.hass.async_block_till_done()
        self.assertEqual(len(self.coffee_orders()), 1)
        self.assertEqual(self.engine.store.data["batches"][batch["id"]]["status"], "ready")
        self.assertEqual(self.engine.notification_delivery["failed"], 3)
        self.transport.assert_not_awaited()

    async def test_disabled_events_and_no_destinations_do_not_notify(self):
        from custom_components.reorder.notifications import async_deliver
        await self.configure_notification_destinations(events=[])
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        await self.prepare()
        await self.hass.async_block_till_done()
        self.assertEqual(self.notification_calls, [])
        await self.engine.update_notifications({"persistent": False})
        result = await async_deliver(self.engine, "cart_added", "No recipients", test=True)
        self.assertEqual(result, {"sent": 0, "failed": 0})
        self.transport.assert_not_awaited()

    async def test_test_notification_uses_saved_settings_without_mutation_or_purchase(self):
        from custom_components.reorder.frontend import websocket_notification_test
        await self.configure_notification_destinations(events=[])
        before = deepcopy(self.engine.store.data)
        connection = await self.admin_command(websocket_notification_test)
        connection.send_error.assert_not_called()
        self.assertEqual(connection.send_result.call_args.args[1], {"sent": 3, "failed": 0})
        self.assertEqual(before, self.engine.store.data)
        self.assertTrue(all("test" in data["message"].lower() for _, _, data in self.notification_calls))
        self.transport.assert_not_awaited()

    async def test_notification_settings_validate_allowlist_preserve_preferences_and_rollback(self):
        import voluptuous as vol
        original = deepcopy(self.engine.store.data)
        for values in ({"notify_services": ["reorder.submit_batch_zinc"]},
                       {"kiosk_services": ["esphome.kitchen_shizuku_command"]},
                       {"notify_entities": ["script.purchase"]}, {"kiosk_duration": -1},
                       {"kiosk_scale": 9}, {"kiosk_scale": "nan"}, {"events": ["purchase"]}):
            with self.assertRaises(vol.Invalid):
                await self.engine.update_notifications(values)
        self.assertEqual(original, self.engine.store.data)
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.engine.update_notifications({"persistent": False})
        self.assertEqual(original, self.engine.store.data)
        await self.engine.update_notifications({"persistent": False, "notify_services": ["notify.phone", "notify.phone"]})
        self.assertEqual(self.engine.store.data["preferences"]["notification_settings"]["notify_services"], ["notify.phone"])
        await self.engine.update_preferences(strategy="manual", weekday=6, hour=10, rolling_hours=48)
        self.assertFalse(self.engine.store.data["preferences"]["notification_settings"]["persistent"])

    async def test_notification_settings_survive_reload_and_discover_kiosk_only_actions(self):
        from custom_components.reorder.frontend import panel_data
        await self.configure_notification_destinations()
        self.hass.services.async_register("esphome", "kitchen_shizuku_command", AsyncMock())
        self.hass.services.async_register("esphome", "kitchen_notification_dismiss", AsyncMock())
        snapshot = panel_data(self.engine, self.entry)
        self.assertEqual(snapshot["notification_destinations"]["kiosks"], ["esphome.kitchen_tablet_notification"])
        restored = ReorderStore(self.hass)
        await restored.load()
        self.assertEqual(restored.data["preferences"]["notification_settings"], self.engine.store.data["preferences"]["notification_settings"])
        self.assertNotIn("reorder.submit_batch_zinc", str(snapshot["notification_destinations"]))

    async def test_repeated_status_refresh_does_not_repeat_external_notifications(self):
        await self.configure_notification_destinations(events=["order_status"])
        batch = await self.prepare()
        await self.submit(batch)
        await self.hass.async_block_till_done()
        self.notification_calls.clear()
        self.transport.return_value = {"id": "mock-zinc-id", "status": "order_placed"}
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 3)
        await self.call("refresh_batch_zinc", {"batch_id": batch["id"]})
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 3)

    async def test_unknown_submission_notifies_attention_without_retrying(self):
        await self.configure_notification_destinations(events=["attention"])
        batch = await self.prepare()
        self.transport.side_effect = TimeoutError("synthetic uncertainty")
        with self.assertRaises(TimeoutError):
            await self.submit(batch)
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 3)
        self.assertIn("may already exist", self.notification_calls[-1][2]["message"])
        self.transport.assert_awaited_once()

    async def test_real_notify_entity_without_title_feature_receives_plain_message(self):
        from homeassistant.components import notify
        from homeassistant.setup import async_setup_component
        received = []
        class Display(notify.NotifyEntity):
            _attr_name = "Reorder notify regression"
            _attr_should_poll = False
            async def async_send_message(self, message, title=None):
                received.append((message, title))
        self.assertTrue(await async_setup_component(self.hass, "notify", {}))
        component = self.hass.data[notify.DATA_COMPONENT]
        display = Display()
        await component.async_add_entities([display])
        await self.engine.update_notifications({"persistent": False, "notify_entities": [display.entity_id]})
        from custom_components.reorder.notifications import async_deliver
        report = await async_deliver(self.engine, "cart_added", "Saved cart entry.")
        self.assertEqual(report, {"sent": 1, "failed": 0})
        self.assertEqual(len(received), 1)
        self.assertIn("Saved cart entry", received[0][0])
        self.assertIsNone(received[0][1])
        self.transport.assert_not_awaited()

    async def test_saved_batch_retires_superseded_persistent_cart_notices(self):
        await self.configure_coffee()
        await self.add_shopping_item("coffee")
        saved = self.coffee_orders()[0]
        self.assertIn("reorder_" + saved["id"], self.hass.data["persistent_notification"])
        batch = await self.prepare()
        await self.hass.async_block_till_done()
        self.assertNotIn("reorder_" + saved["id"], self.hass.data["persistent_notification"])
        self.assertIn("reorder_batch_" + batch["id"], self.hass.data["persistent_notification"])
        self.transport.assert_not_awaited()

    async def test_older_kiosk_schema_receives_only_declared_arguments(self):
        import voluptuous as vol
        from custom_components.reorder.notifications import async_deliver
        await self.configure_notification_destinations()
        received = []
        async def kiosk(call):
            received.append(dict(call.data))
        self.hass.services.async_register("esphome", "kitchen_tablet_notification", kiosk,
            schema=vol.Schema({vol.Required("message"): str, vol.Required("title"): str,
                               vol.Required("duration"): int}))
        report = await async_deliver(self.engine, "cart_added", "Saved locally.")
        self.assertEqual(report, {"sent": 3, "failed": 0})
        self.assertEqual(set(received[0]), {"message", "title", "duration"})
        self.assertEqual(received[0]["duration"], 45)

    async def test_confirmed_delivery_notifies_only_once_and_reports_sandbox_mode(self):
        await self.configure_notification_destinations(events=["delivery"])
        batch, saved = await self.delivered_coffee()
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 3)
        self.assertIn("Sandbox simulation", self.notification_calls[-1][2]["message"])
        self.assertTrue(self.hass.data["shopping_list"].items[-1]["complete"])
        await self.engine.refresh_batch_zinc(batch["id"], ZincClient(None, "zn_test_fake"))
        await self.hass.async_block_till_done()
        self.assertEqual(len(self.notification_calls), 3)

    async def test_cart_save_failure_never_sends_added_notification(self):
        await self.configure_notification_destinations()
        await self.configure_coffee()
        with patch.object(self.engine.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.engine.match_new_item({"id": "unsaved-item", "name": "coffee"})
        await self.hass.async_block_till_done()
        self.assertEqual(self.notification_calls, [])
        self.assertEqual(self.coffee_orders(), [])
        self.transport.assert_not_awaited()

    async def test_missing_shipping_address_blocks_submission(self):
        batch = await self.prepare()
        self.hass.config_entries.async_update_entry(self.entry, options={"zinc_api_key": "zn_test_not-a-real-key"})
        with self.assertRaisesRegex(HomeAssistantError, "shipping"):
            await self.submit(batch)
        self.transport.assert_not_awaited()

    async def test_old_storage_loads_without_version_migration(self):
        legacy = {"products": {}, "orders": {"1": order()}, "seen_items": ["old-item"]}
        store = ReorderStore(self.hass)
        with patch.object(store._store, "async_load", AsyncMock(return_value=legacy)):
            await store.load()
        self.assertEqual(store.data["orders"], legacy["orders"])
        self.assertEqual(store.data["batches"], {})
        self.assertEqual(store.data["seen_items"], ["old-item"])


class ZincPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_reuses_idempotency_key_and_preserves_payload(self):
        client = ZincClient(None, "zn_test_not-a-real-key")
        client.request = AsyncMock(return_value={"id": "mock"})
        for _ in range(2):
            await client.create_batch_order({"id": "stable", "max_price": 12.5}, [order()], {})
        payloads = [call.args[2] for call in client.request.await_args_list]
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[0]["idempotency_key"], "reorder-batch-stable")

    async def test_single_order_idempotency_key_is_unchanged(self):
        client = ZincClient(None, "zn_test_not-a-real-key")
        client.request = AsyncMock(return_value={"id": "mock"})
        await client.create_order(order(), {})
        self.assertEqual(client.request.await_args.args[2]["idempotency_key"], "1")

    async def test_batch_rejects_empty_oversized_or_non_https_products(self):
        client = ZincClient(None, "zn_test_not-a-real-key")
        client.request = AsyncMock()
        for orders in ([], [order(i) for i in range(11)], [order() | {"product_id": "http://example.com"}]):
            with self.subTest(count=len(orders)):
                with self.assertRaises(ValueError):
                    await client.create_batch_order({"id": "stable", "max_price": 12.5}, orders, {})
        client.request.assert_not_awaited()


class DashboardConfigTest(unittest.TestCase):
    def test_dashboard_uses_native_cards_and_never_submits_purchases(self):
        import yaml
        config = yaml.safe_load((Path(__file__).resolve().parents[1] / "dashboards/reorder.yaml").read_text())
        actions = []
        allowed_cards = {"markdown", "entities", "button", "horizontal-stack", "sections", "grid", "heading"}
        def inspect(node):
            if isinstance(node, dict):
                if "type" in node:
                    self.assertIn(node["type"], allowed_cards)
                if "perform_action" in node:
                    actions.append(node)
                    self.assertIn(node["perform_action"], {"button.press", "reorder.preview_batch", "reorder.prepare_batch"})
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)
        inspect(config)
        cancel = next(action for action in actions if action.get("target", {}).get("entity_id") == "button.reorder_cancel_batch")
        self.assertIn("confirmation", cancel)
        self.assertIn("queued orders", cancel["confirmation"]["text"])


class FulfillmentDataTest(unittest.TestCase):
    def test_exact_delivery_mapping_rejects_inferred_missing_conflicting_and_failed_lines(self):
        from custom_components.reorder.fulfillment import fulfillment_snapshot, item_delivery_confirmed
        response = {"items": [{"id": "item-1", "url": "https://example.com/item", "quantity": 1,
                               "status": "ordered", "tracking_number_ids": ["package-1"]}],
                    "tracking_numbers": [{"id": "package-1", "status": "delivered",
                                          "order_item_ids": ["item-1"], "item_mapping": "exact"}]}
        snapshot = fulfillment_snapshot(response)
        self.assertTrue(item_delivery_confirmed(snapshot["items"][0], snapshot))
        for change in (dict(item_mapping="inferred"), dict(order_item_ids=None),
                       dict(status="in_transit"), dict(id="other-package")):
            altered = deepcopy(snapshot)
            altered["shipments"][0].update(change)
            self.assertFalse(item_delivery_confirmed(altered["items"][0], altered))
        for status in ("failed", "skipped", "cancelled"):
            altered = deepcopy(snapshot)
            altered["items"][0]["status"] = status
            self.assertFalse(item_delivery_confirmed(altered["items"][0], altered))
        altered = deepcopy(snapshot)
        altered["items"].append(deepcopy(altered["items"][0]))
        self.assertFalse(item_delivery_confirmed(altered["items"][0], altered))
        altered = deepcopy(snapshot)
        altered["shipments"].append(deepcopy(altered["shipments"][0]))
        self.assertFalse(item_delivery_confirmed(altered["items"][0], altered))


    def test_duplicate_product_mapping_never_authorizes_list_completion(self):
        from custom_components.reorder.fulfillment import fulfillment_snapshot, receipt_eligible
        saved = order() | {"shopping_item_id": "source", "zinc_environment": "sandbox", "zinc_order_id": "mock"}
        batch = {"status": "order_placed", "zinc_environment": "sandbox", "zinc_order_id": "mock", "fulfillment": fulfillment_snapshot({"items": [{"id": "provider", "url": saved["product_id"], "quantity": 2, "status": "ordered"}]})}
        self.assertTrue(receipt_eligible(saved, batch, [saved]))
        duplicate = saved | {"id": "another"}
        self.assertFalse(receipt_eligible(saved, batch, [saved, duplicate]))
        batch["fulfillment"]["items"].append(dict(batch["fulfillment"]["items"][0]))
        self.assertFalse(receipt_eligible(saved, batch, [saved]))


class ZincErrorPrivacyTest(unittest.IsolatedAsyncioTestCase):
    async def test_http_errors_retain_only_machine_code_and_status(self):
        from custom_components.reorder.zinc import ZincRequestError
        response = MagicMock(status=422)
        response.json = AsyncMock(return_value={"code": "invalid_shipping_address", "message": "zn_test_private at a private address", "shipping_address": {"first_name": "private"}})
        session = MagicMock()
        session.request.return_value.__aenter__.return_value = response
        client = ZincClient(session, "zn_test_fake")
        with self.assertRaises(ZincRequestError) as error:
            await client.request("POST", "/orders", {})
        self.assertEqual(error.exception.code, "invalid_shipping_address")
        self.assertEqual(error.exception.status, 422)
        self.assertNotIn("private", str(error.exception))
