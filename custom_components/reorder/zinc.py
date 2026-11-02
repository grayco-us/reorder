"""Minimal Zinc REST client. Never logs credentials or shipping details."""
import aiohttp
from homeassistant.exceptions import HomeAssistantError
from .fulfillment import safe_code

API = "https://api.zinc.com"


class ZincRequestError(HomeAssistantError):
    """Keep only status and a machine-readable code, never raw error text."""
    def __init__(self, status, code=None):
        self.status, self.code = status, code
        super().__init__(f"Zinc returned HTTP {status}" + (f" ({code})" if code else ""))


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
                    code = None
                    try:
                        body = await response.json()
                        if isinstance(body, dict):
                            code = safe_code(body.get("code") or body.get("error_code"))
                    except (ValueError, aiohttp.ClientError):
                        pass
                    raise ZincRequestError(response.status, code)
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

    async def create_batch_order(self, batch, orders, address):
        """Submit a single retailer order containing multiple line items."""
        if not orders or len(orders) > 10:
            raise ValueError("Zinc batch must have 1–10 line items")
        products = []
        for order in orders:
            url = order["product_id"]
            if not url.startswith("https://"):
                raise ValueError("All Zinc products must use HTTPS URLs")
            products.append({"url": url, "quantity": order["quantity"]})
        return await self.request("POST", "/orders", {
            "products": products,
            "max_price": round(batch["max_price"] * 100),
            "idempotency_key": "reorder-batch-" + batch["id"],
            "shipping_address": address,
        })
