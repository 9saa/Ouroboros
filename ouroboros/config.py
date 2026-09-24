"""Load settings.json. Creates it with defaults if missing."""

import json5
import os

DEFAULTS = {
    "cookies_file": "cookies.json",
    "user_id": 0,
    "log_level": "INFO",
    "check_interval": 0.8,
    "resale_check_interval": 15.0,
    "items_per_page": 100,
    "max_pages": 5,
    "asset_type_ids": [8, 18, 19, 41, 42, 43, 44, 45, 46, 47],
    "forbidden_phrases": ["do not buy", "do not purchase", "do not delete"],
    "max_price": 0,
    "max_retries": 20,
    "purchase_source": "web-modal-v3",
}


def load_settings(path: str = "settings.json") -> dict:
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json5.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError) as e:
            print(f"[config] could not read {path}: {e} - using defaults")
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json5.dump(DEFAULTS, f, indent=2)
        except OSError as e:
            print(f"[config] could not write {path}: {e}")

    merged = dict(DEFAULTS)
    merged.update(data)
    return merged
