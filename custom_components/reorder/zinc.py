"""Minimal Zinc REST client. Never logs credentials or shipping details."""
import aiohttp
from homeassistant.exceptions import HomeAssistantError

API = "https://api.zinc.com"


class ZincClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str):
        self.session, self.api_key = session, api_key

    async def request(self, method: str, path: str, payload=None):
        try:
            async with self.session.request(
                method, API + path,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                # Do not persist sensitive response bodies from failed requests.
                if response.status >= 400:
                    raise HomeAssistantError(f"Zinc returned HTTP {response.status}")
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError("Unable to communicate with Zinc") from err

    async def create_order(self, order, address):
        return await self.request("POST", "/orders", {
            "products": [{"url": order["product_id"], "quantity": order["quantity"]}],
            "max_price": round(order["max_price"] * 100),
            "idempotency_key": order["id"],
            "shipping_address": address,
        })

    async def get_order(self, zinc_id):
        from urllib.parse import quote
        return await self.request("GET", "/orders/" + quote(str(zinc_id), safe=""))
