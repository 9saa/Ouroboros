"""Hexium HTTP client: inventory, resale, ownership, prepare, confirm."""

import httpx

INVENTORY_URL = (
    "https://hexium.zip/users/inventory/list-json"
    "?userId=1&assetTypeId={asset_type}&cursor={cursor}&itemsPerPage={per_page}"
)
RESALE_URL = "https://hexium.zip/apisite/economy/v1/assets/{asset_id}/resale-data"
IS_OWNED_URL = (
    "https://hexium.zip/apisite/inventory/v1/users/{user_id}"
    "/items/asset/{asset_id}/is-owned"
)
PREPARE_URL = "https://hexium.zip/apisite/economy/v1/purchases/prepare/{asset_id}"
CONFIRM_URL = "https://hexium.zip/apisite/economy/v1/purchases/products/{asset_id}"
ITEM_URL = "https://hexium.zip/catalog/{asset_id}/x"


class ApiError(Exception):
    pass


class HexiumApi:
    def __init__(self, cookies: list) -> None:
        self._client = httpx.Client(
            http2=True,
            timeout=httpx.Timeout(20.0, connect=5.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=60.0,
            ),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) "
                    "Gecko/20100101 Firefox/156.0"
                ),
            },
        )
        for c in cookies:
            try:
                self._client.cookies.set(
                    c["name"], c["value"],
                    domain=c.get("domain", "hexium.zip"),
                    path=c.get("path", "/"),
                )
            except (KeyError, TypeError):
                pass

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- inventory --------------------------------------------------------

    def fetch_inventory_page(self, asset_type: int, cursor: str = "",
                             per_page: int = 100) -> dict:
        url = INVENTORY_URL.format(
            asset_type=asset_type, cursor=cursor, per_page=per_page,
        )
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            raise ApiError(f"inventory fetch failed: {e}") from e
        if r.status_code != 200:
            raise ApiError(f"inventory status {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ApiError(f"inventory JSON parse failed: {e}") from e

    # ---- resale / ownership ----------------------------------------------

    def fetch_resale_data(self, asset_id: int) -> dict:
        url = RESALE_URL.format(asset_id=asset_id)
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            raise ApiError(f"resale-data fetch failed: {e}") from e
        if r.status_code != 200:
            raise ApiError(f"resale-data status {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ApiError(f"resale-data JSON parse failed: {e}") from e

    def is_owned(self, user_id: int, asset_id: int) -> bool:
        url = IS_OWNED_URL.format(user_id=user_id, asset_id=asset_id)
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            raise ApiError(f"is-owned fetch failed: {e}") from e
        if r.status_code != 200:
            raise ApiError(f"is-owned status {r.status_code}")
        body = r.text.strip()
        if body.lower() in ("true", "false"):
            return body.lower() == "true"
        try:
            return bool(r.json())
        except ValueError:
            return False

    # ---- purchase ---------------------------------------------------------

    def prepare(self, asset_id: int, csrf: str) -> dict:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://hexium.zip",
            "Referer": ITEM_URL.format(asset_id=asset_id),
            "x-csrf-token": csrf,
        }
        try:
            r = self._client.post(
                PREPARE_URL.format(asset_id=asset_id), headers=headers,
            )
        except httpx.HTTPError as e:
            raise ApiError(f"prepare failed: {e}") from e
        if r.status_code != 200:
            raise ApiError(f"prepare status {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ApiError(f"prepare JSON parse failed: {e}") from e

    def confirm(self, asset_id: int, csrf: str, token: str,
                proof: str, interaction: str, price: int,
                source: str) -> dict:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://hexium.zip",
            "Referer": ITEM_URL.format(asset_id=asset_id),
            "x-csrf-token": csrf,
            "x-purchase-source": source,
            "x-purchase-token": token,
            "x-purchase-proof": proof,
            "x-purchase-interaction": interaction,
        }
        body = {
            "assetId": asset_id,
            "expectedPrice": price,
            "expectedSellerId": 1,
            "userAssetId": None,
            "expectedCurrency": 1,
        }
        try:
            r = self._client.post(
                CONFIRM_URL.format(asset_id=asset_id),
                headers=headers, json=body,
            )
        except httpx.HTTPError as e:
            raise ApiError(f"confirm failed: {e}") from e
        try:
            return r.json()
        except ValueError as e:
            raise ApiError(f"confirm JSON parse failed: {e}") from e
