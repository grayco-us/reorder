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
