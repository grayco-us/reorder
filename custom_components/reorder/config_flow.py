"""Native UI setup and catalog administration for Reorder by Grayco."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectOptionDict

from .const import DOMAIN
from .core import norm

RETAILERS = SelectSelector(
    SelectSelectorConfig(
        options=[
            SelectOptionDict(value="zinc", label="Zinc — supported purchasing provider"),
            SelectOptionDict(value="kroger", label="Kroger — cart integration planned"),
            SelectOptionDict(value="other", label="Other — catalog only"),
        ],
        mode="dropdown",
    )
)


def product_schema(product: dict | None = None) -> vol.Schema:
    """Form for an approved product. Aliases are entered comma-separated."""
    p = product or {}
    aliases = p.get("aliases", [])
    alias_text = aliases if isinstance(aliases, str) else ", ".join(aliases)
    return vol.Schema({
        vol.Required("name", default=p.get("name", "")): cv.string,
        vol.Optional("aliases", default=alias_text): cv.string,
        vol.Required("retailer", default=p.get("retailer", "zinc")): RETAILERS,
        vol.Required("product_id", default=p.get("product_id", "")): cv.string,
        vol.Optional("substitute_1", default=p.get("substitutes", [""])[0] if p.get("substitutes") else ""): cv.string,
        vol.Optional("substitute_2", default=(p.get("substitutes", ["", ""])[1] if len(p.get("substitutes", [])) > 1 else "")): cv.string,
        vol.Required("quantity", default=p.get("quantity", 1)): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Required("max_price", default=p.get("max_price", 50.0)): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=10000)),
        vol.Required("cooldown_hours", default=p.get("cooldown_hours", 168)): vol.All(vol.Coerce(int), vol.Range(min=1, max=8760)),
        vol.Required("enabled", default=p.get("enabled", True)): cv.boolean,
    })


class ReorderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one local Reorder integration."""
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            await self.async_set_unique_id("reorder_main")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Reorder", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    def async_get_options_flow(config_entry):
        return ReorderOptionsFlow()


class ReorderOptionsFlow(config_entries.OptionsFlow):
    """Edit the locally stored catalog from Settings > Integrations > Configure."""

    def _engine(self):
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

    def _products(self):
        return self._engine().store.data["products"]

    async def async_step_init(self, user_input=None) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["add_product", "edit_product", "remove_product", "zinc_settings", "batch_settings"])

    async def async_step_add_product(self, user_input=None) -> FlowResult:
        if user_input is not None:
            name = user_input["name"].strip()
            if not name or not user_input["product_id"].strip():
                return self.async_show_form(step_id="add_product", data_schema=product_schema(), errors={"base": "required_fields"})
            if norm(name) in self._products():
                return self.async_show_form(step_id="add_product", data_schema=product_schema(), errors={"base": "already_exists"})
            try:
                await self._save_product(user_input, create_only=True)
            except (ValueError, vol.Invalid):
                return self.async_show_form(step_id="add_product", data_schema=product_schema(user_input), errors={"base": "invalid_product"})
            return self.async_create_entry(title="Product added", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="add_product", data_schema=product_schema())

    async def async_step_edit_product(self, user_input=None) -> FlowResult:
        products = self._products()
        if not products:
            return self.async_abort(reason="empty_catalog")
        if user_input is not None:
            self._selected_key = user_input["product"]
            return await self.async_step_update_product()
        return self.async_show_form(step_id="edit_product", data_schema=vol.Schema({
            vol.Required("product"): vol.In({k: p["name"] for k, p in products.items()})
        }))

    async def async_step_update_product(self, user_input=None) -> FlowResult:
        current = self._products().get(self._selected_key)
        if current is None:
            return self.async_abort(reason="product_missing")
        if user_input is not None:
            new_key = norm(user_input["name"])
            if not new_key or not user_input["product_id"].strip():
                return self.async_show_form(step_id="update_product", data_schema=product_schema(current), errors={"base": "required_fields"})
            if new_key != self._selected_key and new_key in self._products():
                return self.async_show_form(step_id="update_product", data_schema=product_schema(current), errors={"base": "already_exists"})
            try:
                await self._save_product(user_input, original_name=current["name"])
            except (ValueError, vol.Invalid):
                return self.async_show_form(step_id="update_product", data_schema=product_schema(user_input), errors={"base": "invalid_product"})
            return self.async_create_entry(title="Product updated", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="update_product", data_schema=product_schema(current))

    async def async_step_remove_product(self, user_input=None) -> FlowResult:
        products = self._products()
        if not products:
            return self.async_abort(reason="empty_catalog")
        if user_input is not None:
            await self._engine().remove_product(user_input["product"])
            return self.async_create_entry(title="Product removed", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="remove_product", data_schema=vol.Schema({
            vol.Required("product"): vol.In({k: p["name"] for k, p in products.items()})
        }))

    async def _save_product(self, data, **extra):
        await self._engine().upsert_product(
            name=data["name"],
            aliases=[s.strip() for s in data["aliases"].split(",") if s.strip()],
            retailer=data["retailer"],
            product_id=data["product_id"],
            quantity=data["quantity"],
            substitutes=[data.get("substitute_1", ""), data.get("substitute_2", "")],
            max_price=data["max_price"],
            cooldown_hours=data["cooldown_hours"],
            enabled=data["enabled"], **extra,
        )

    async def async_step_zinc_settings(self, user_input=None) -> FlowResult:
        """Configure test or live Zinc access; live always defaults off."""
        options = self.config_entry.options
        fields = ["first_name", "last_name", "address_line1", "city", "state", "postal_code", "phone_number"]
        schema = {
            vol.Optional("zinc_api_key", default=options.get("zinc_api_key", "")): cv.string,
            vol.Required("zinc_live_enabled", default=options.get("zinc_live_enabled", False)): cv.boolean,
        }
        for field in fields:
            schema[vol.Optional("ship_" + field, default=options.get("ship_" + field, ""))] = cv.string
        if user_input is not None:
            if user_input["zinc_live_enabled"] and not user_input["zinc_api_key"].startswith("zn_live_"):
                return self.async_show_form(step_id="zinc_settings", data_schema=vol.Schema(schema), errors={"base": "live_key_required"})
            # All parameters saved inside HA config entry options, not source code.
            return self.async_create_entry(title="Zinc settings updated", data={**options, **user_input})
        return self.async_show_form(step_id="zinc_settings", data_schema=vol.Schema(schema))

    async def async_step_batch_settings(self, user_input=None) -> FlowResult:
        """Configure schedule; scheduled runs only prepare batches for review."""
        settings = self._engine().store.data.get("batch_settings", {})
        schema = vol.Schema({
            vol.Required("strategy", default=settings.get("strategy", "manual")): vol.In({
                "manual": "Manual batching", "weekly": "Weekly review", "rolling": "Rolling window"}),
            vol.Required("weekday", default=settings.get("weekday", 6)): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
            vol.Required("hour", default=settings.get("hour", 10)): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
            vol.Required("rolling_hours", default=settings.get("rolling_hours", 48)): vol.All(vol.Coerce(int), vol.Range(min=1, max=336)),
        })
        if user_input is not None:
            await self._engine().update_preferences(**user_input,
                sync_shopping_list=self._engine().store.data.get("preferences", {}).get("sync_shopping_list", True))
            return self.async_create_entry(title="Batch schedule saved", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="batch_settings", data_schema=schema)
