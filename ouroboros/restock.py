"""The restock module.

Periodically polls resale-data for every limited item. When an item's
assetStock increases, it attempts to buy - but only if the user doesn't
already own it and there's actually stock available.

Runs on its own schedule and thread pool so it never competes with the
Sniper's inventory fetches.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from ouroboros.api import ApiError, HexiumApi
from ouroboros.challenge import compute_proof
from ouroboros.coordinator import claim, release
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

_INVENTORY_WORKERS = 5
_RESALE_WORKERS = 6


class Restock(Module):
    name = "Restock"

    def __init__(self, settings: dict) -> None:
        super().__init__(settings)
        self.log = Logger("Restock")
        self._api: HexiumApi | None = None
        self._csrf: str | None = None
        self._user_id: int = 0
        self._stock_cache: dict[int, int] = {}
        self._owned: set[int] = set()
        self._resale_pool: ThreadPoolExecutor | None = None

        self.stats = {
            "restocks": 0,
            "bought": 0,
            "failed": 0,
            "skipped_owned": 0,
            "skipped_no_stock": 0,
            "last_purchase": "-",
        }

    # ---- main loop --------------------------------------------------------

    def run(self) -> None:
        self.log.info("Starting up")

        self._user_id = int(self.settings.get("user_id", 0))
        if not self._user_id:
            self.log.error(
                "user_id not set in settings.json - restock checks disabled"
            )
            return

        try:
            cookies = load_cookies(self.settings["cookies_file"])
        except (OSError, ValueError) as e:
            self.log.error(f"Cannot load cookies: {e}")
            return

        self._csrf = extract_csrf(cookies)
        if not self._csrf:
            self.log.error("No CSRF token in rbxcsrf4 cookie")
            return

        self._api = HexiumApi(cookies)
        self._resale_pool = ThreadPoolExecutor(
            max_workers=_RESALE_WORKERS, thread_name_prefix="restock",
        )

        # Initial snapshot
        items = self._fetch_inventory()
        if not items:
            self.log.error("No inventory items - aborting")
            return

        self._prime_stock_cache(items)
        self._prime_owned(items)
        if self.should_stop():
            return

        interval = float(self.settings.get("resale_check_interval", 15.0))
        self.log.info(
            f"Watching {len(items)} items every {interval:.0f}s "
            f"({len(self._owned)} owned)"
        )

        while not self.should_stop():
            self._check_restocks(items)
            # Refresh inventory list occasionally so new uploads are included
            self.sleep(interval)
            items = self._fetch_inventory() or items

        if self._resale_pool:
            self._resale_pool.shutdown(wait=False)
        if self._api:
            self._api.close()
        self.log.info(
            f"Stopped. restocks={self.stats['restocks']} "
            f"bought={self.stats['bought']} failed={self.stats['failed']} "
            f"skipped_owned={self.stats['skipped_owned']} "
            f"skipped_no_stock={self.stats['skipped_no_stock']}"
        )

    # ---- warm up ----------------------------------------------------------

    def _prime_stock_cache(self, items: list) -> None:
        self.log.info(f"Priming stock cache for {len(items)} items")

        def probe(item):
            try:
                data = self._api.fetch_resale_data(item["id"])
                return item["id"], int(data.get("assetStock", 0))
            except ApiError:
                return item["id"], None

        results = list(self._resale_pool.map(probe, items))
        for aid, stock in results:
            if stock is not None:
                self._stock_cache[aid] = stock
        self.log.info(f"Stock cache: {len(self._stock_cache)} entries")

    def _prime_owned(self, items: list) -> None:
        self.log.info(f"Priming ownership for {len(items)} items")

        def probe(item):
            try:
                return item["id"], self._api.is_owned(
                    self._user_id, item["id"])
            except ApiError:
                return item["id"], False

        results = list(self._resale_pool.map(probe, items))
        for aid, owned in results:
            if owned:
                self._owned.add(aid)
        self.log.info(f"Ownership: {len(self._owned)} items already owned")

    # ---- restock detection ------------------------------------------------

    def _check_restocks(self, items: list) -> None:
        if not items:
            return

        def probe(item):
            try:
                return item, self._api.fetch_resale_data(item["id"])
            except ApiError:
                return item, None

        results = list(self._resale_pool.map(probe, items))

        for item, data in results:
            if data is None:
                continue
            aid = item["id"]
            new_stock = int(data.get("assetStock", 0))
            old_stock = self._stock_cache.get(aid, new_stock)

            if new_stock > old_stock:
                self.log.info(
                    f"Restock: {item['name']} (id={aid}, "
                    f"stock {old_stock}->{new_stock})"
                )
                self.stats["restocks"] += 1
                self._handle_restock(item, data)

            self._stock_cache[aid] = new_stock

    def _handle_restock(self, item: dict, resale_data: dict) -> None:
        aid = item["id"]

        # Already own it?
        if aid in self._owned:
            self.log.debug(f"Already own {item['name']}, skipping")
            self.stats["skipped_owned"] += 1
            return

        try:
            if self._api.is_owned(self._user_id, aid):
                self._owned.add(aid)
                self.stats["skipped_owned"] += 1
                self.log.debug(f"Now own {item['name']}, skipping")
                return
        except ApiError:
            pass

        # Is there actually stock?
        remaining = int(resale_data.get("numberRemaining", 0))
        if remaining <= 0:
            self.log.debug(
                f"Restock signal for {item['name']} but numberRemaining=0"
            )
            self.stats["skipped_no_stock"] += 1
            return

        # Local filters
        name_lower = item["name"].lower()
        for phrase in self.settings.get("forbidden_phrases", []):
            if phrase.lower() in name_lower:
                return

        max_price = int(self.settings.get("max_price", 0))
        if max_price > 0 and item["price"] > max_price:
            return

        # Coordinate with Sniper - only one of us attempts
        if not claim(aid):
            self.log.debug(
                f"Skipping {item['name']} - already in progress"
            )
            return

        try:
            self.log.info(
                f"RESTOCK: {item['name']} (id={aid}, "
                f"{item['price']}R$, {remaining} available)"
            )
            self._attempt_purchase(item)
        finally:
            release(aid)

    def _attempt_purchase(self, item: dict) -> None:
        max_retries = int(self.settings.get("max_retries", 20))
        last_reason = "unknown"

        for attempt in range(1, max_retries + 1):
            if self.should_stop():
                return
            outcome, reason = self._purchase(item)
            if outcome == "success":
                self.stats["bought"] += 1
                self.stats["last_purchase"] = item["name"]
                self._owned.add(item["id"])
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

    # ---- inventory --------------------------------------------------------

    def _fetch_inventory(self) -> list:
        types = self.settings["asset_type_ids"]
        max_pages = int(self.settings.get("max_pages", 5))
        per_page = int(self.settings.get("items_per_page", 100))
        if not types:
            return []
        items = []
        workers = min(len(types), _INVENTORY_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._fetch_type, t, max_pages, per_page)
                       for t in types]
            for f in futures:
                try:
                    items.extend(f.result())
                except ApiError as e:
                    self.log.debug(f"inventory type fetch failed: {e}")
        # Deduplicate by ID
        seen = set()
        out = []
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                out.append(item)
        return out

    def _fetch_type(self, asset_type: int, max_pages: int,
                    per_page: int) -> list:
        out = []
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

    # ---- purchase ---------------------------------------------------------

    def _purchase(self, item: dict):
        aid = item["id"]
        price = item["price"]
        source = self.settings.get("purchase_source", "web-modal-v3")

        try:
            prepared = self._api.prepare(aid, self._csrf)
        except ApiError as e:
            return "retry", f"prepare failed: {e}"

        token = prepared.get("purchaseToken")
        if not token:
            return "retry", "no purchaseToken in prepare"

        challenge = prepared.get("challenge")
        if not challenge:
            return "retry", "no challenge in prepare"

        proof = compute_proof(challenge, aid)

        wait_ms = int(prepared.get("minWaitMs", 300))
        time.sleep((wait_ms + 50) / 1000.0)

        try:
            result = self._api.confirm(aid, self._csrf, token, proof,
                                        price, source)
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