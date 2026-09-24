"""The sniper module.

Watches the admin inventory for new drops. Any item ID not seen in the
previous cycle is purchased immediately using the v4 challenge flow.

A fetch is only considered valid if every asset type returned successfully.
Partial fetches are discarded so they cannot corrupt the baseline and cause
a false flood of "new" items on the next cycle.
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor

from ouroboros.api import ApiError, HexiumApi
from ouroboros.challenge import compute_interaction_hash, compute_proof
from ouroboros.log import Logger
from ouroboros.modules import Module
from ouroboros.session import extract_csrf, load_cookies


_PERMANENT = (
    "not authenticated",
    "not enough robux",
    "insufficient",
    "no longer for sale",
    "not for sale",
    "already owned",
)

_INVENTORY_WORKERS = 10
_MAX_NEW_PER_CYCLE = 20


class Sniper(Module):
    name = "Sniper"

    def __init__(self, settings: dict) -> None:
        super().__init__(settings)
        self.log = Logger("Sniper")
        self._api: HexiumApi | None = None
        self._csrf: str | None = None
        self._user_id: int = 0
        self._last_ids: set[int] = set()

        self.stats = {
            "seen": 0,
            "bought": 0,
            "failed": 0,
            "bad_fetches": 0,
            "last_purchase": "-",
        }

    # ---- main loop --------------------------------------------------------

    def run(self) -> None:
        self.log.info("Starting up")

        self._user_id = int(self.settings.get("user_id", 0))
        if not self._user_id:
            self.log.error(
                "user_id is not set in settings.json. "
                "Add your Hexium user ID (the number in your profile URL)."
            )
            return

        try:
            cookies = load_cookies(self.settings["cookies_file"])
        except (OSError, ValueError) as e:
            self.log.error(f"Cannot load cookies: {e}")
            return

        self._csrf = extract_csrf(cookies)
        if not self._csrf:
            self.log.error("No CSRF token found in rbxcsrf4 cookie")
            return

        self._api = HexiumApi(cookies)

        if not self._establish_baseline():
            self.log.error("Could not establish baseline; aborting")
            return

        interval = float(self.settings.get("check_interval", 0.8))

        while not self.should_stop():
            try:
                items, clean = self._fetch_all()
            except ApiError as e:
                self.log.warn(f"Fetch failed: {e}")
                self.sleep(2.0)
                continue

            if not clean:
                self.stats["bad_fetches"] += 1
                self.log.debug("Partial fetch - skipping cycle")
                self.sleep(interval)
                continue

            current_ids = {i["id"] for i in items}
            new_ids = current_ids - self._last_ids

            if len(new_ids) > _MAX_NEW_PER_CYCLE:
                self.log.warn(
                    f"{len(new_ids)} items flagged new - re-baselining"
                )
                self._last_ids = current_ids
                self.sleep(interval)
                continue

            if new_ids:
                by_id = {i["id"]: i for i in items}
                for asset_id in new_ids:
                    if self.should_stop():
                        break
                    item = by_id.get(asset_id)
                    if item is not None:
                        self._handle_new(item)

            self._last_ids = current_ids
            self.sleep(interval)

        if self._api:
            self._api.close()
        self.log.info(
            f"Stopped. seen={self.stats['seen']} "
            f"bought={self.stats['bought']} "
            f"failed={self.stats['failed']} "
            f"bad_fetches={self.stats['bad_fetches']}"
        )

    # ---- baseline ---------------------------------------------------------

    def _establish_baseline(self) -> bool:
        self.log.info("Warming up")
        for attempt in range(1, 6):
            if self.should_stop():
                return False
            try:
                items, clean = self._fetch_all()
            except ApiError as e:
                self.log.warn(f"Baseline attempt {attempt}: {e}")
                self.sleep(1.0)
                continue

            if clean and items:
                self._last_ids = {i["id"] for i in items}
                self.log.info(
                    f"Tracking {len(self._last_ids)} limited items"
                )
                return True

            self.log.warn(
                f"Baseline attempt {attempt}: "
                f"{'partial fetch' if not clean else 'empty result'}"
            )
            self.sleep(1.0)

        return False

    # ---- inventory --------------------------------------------------------

    def _fetch_all(self) -> tuple[list[dict], bool]:
        types = self.settings["asset_type_ids"]
        max_pages = int(self.settings.get("max_pages", 5))
        per_page = int(self.settings.get("items_per_page", 100))
        if not types:
            return [], True

        items: list[dict] = []
        failed = 0
        workers = min(len(types), _INVENTORY_WORKERS)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._fetch_type, t, max_pages, per_page): t
                for t in types
            }
            for f in futures:
                try:
                    items.extend(f.result())
                except ApiError as e:
                    failed += 1
                    self.log.debug(f"type {futures[f]} fetch failed: {e}")

        return items, failed == 0

    def _fetch_type(self, asset_type: int, max_pages: int,
                    per_page: int) -> list[dict]:
        out: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            data = self._api.fetch_inventory_page(
                asset_type, cursor, per_page=per_page,
            )
            page = data.get("Data") or {}
            rows = page.get("Items") or []
            if not rows:
                break
            for row in rows:
                tag = (row.get("AssetRestrictionIcon") or {}).get("CssTag", "")
                if "limited" not in tag.lower():
                    continue
                try:
                    out.append({
                        "id": int(row["Item"]["AssetId"]),
                        "name": str(row["Item"]["Name"]),
                        "price": int(
                            (row.get("Product") or {}).get("PriceInRobux", 0)
                        ),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            nxt = page.get("nextPageCursor")
            if not nxt:
                break
            cursor = nxt
        return out

    # ---- new item handling ------------------------------------------------

    def _handle_new(self, item: dict) -> None:
        name_lower = item["name"].lower()
        for phrase in self.settings.get("forbidden_phrases", []):
            if phrase.lower() in name_lower:
                self.log.info(f"Skipping forbidden: {item['name']}")
                return

        max_price = int(self.settings.get("max_price", 0))
        if max_price > 0 and item["price"] > max_price:
            self.log.info(
                f"Skipping expensive: {item['name']} ({item['price']}R$)"
            )
            return

        self.log.info(
            f"NEW: {item['name']} (id={item['id']}, {item['price']}R$)"
        )
        self.stats["seen"] += 1

        max_retries = int(self.settings.get("max_retries", 20))
        last_reason = "unknown"

        for attempt in range(1, max_retries + 1):
            if self.should_stop():
                return
            outcome, reason = self._purchase(item)
            if outcome == "success":
                self.stats["bought"] += 1
                self.stats["last_purchase"] = item["name"]
                self.log.info(f"BOUGHT: {item['name']}")
                return
            if outcome == "stop":
                last_reason = reason
                break
            last_reason = reason
            self.log.warn(f"Retry {attempt}/{max_retries}: {reason}")
            self.sleep(0.5)

        self.stats["failed"] += 1
        self.log.error(f"Failed to buy {item['name']}: {last_reason}")

    # ---- purchase ---------------------------------------------------------

    def _purchase(self, item: dict) -> tuple[str, str]:
        """Returns (outcome, reason). outcome in {success, retry, stop}."""
        asset_id = item["id"]
        price = item["price"]
        source = self.settings.get("purchase_source", "web-modal-v4")

        try:
            prepared = self._api.prepare(asset_id, self._csrf)
        except ApiError as e:
            return "retry", f"prepare failed: {e}"

        token = prepared.get("purchaseToken")
        if not token:
            return "retry", "no purchaseToken in prepare"

        challenge = prepared.get("challenge")
        if not challenge:
            return "retry", "no challenge in prepare"

        salt = prepared.get("salt", "")
        wait_ms = int(prepared.get("minWaitMs", 600))

        timestamp = random.randint(5000, 25000)
        click_x = 683
        click_y = 384

        interaction_hash = compute_interaction_hash(
            challenge, salt, timestamp, click_x, click_y,
        )
        interaction_header = (
            f"{timestamp}:{click_x}:{click_y}:{interaction_hash}"
        )

        proof = compute_proof(
            challenge, salt, asset_id, self._user_id,
            self._csrf, interaction_hash,
        )
        self.log.debug(f"Proof: {proof[:40]}...")

        time.sleep((wait_ms + 50) / 1000.0)

        try:
            result = self._api.confirm(
                asset_id, self._csrf, token, proof,
                interaction_header, price, source,
            )
        except ApiError as e:
            return "retry", f"confirm failed: {e}"

        if result.get("purchased") is True:
            return "success", "purchased"

        errors = result.get("errors") or []
        for err in errors:
            msg = str(err.get("message", "")).lower()
            if any(p in msg for p in _PERMANENT):
                return "stop", msg or "permanent error"
            return "retry", msg or "server error"

        return "retry", "unknown response"
