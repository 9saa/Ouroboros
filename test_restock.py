#!/usr/bin/env python3
import json
from ouroboros.api import HexiumApi
from ouroboros.config import load_settings
from ouroboros.session import load_cookies

settings = load_settings("settings.json")
cookies = load_cookies(settings["cookies_file"])
user_id = int(settings["user_id"])
api = HexiumApi(cookies)

asset_id = int(input("Asset ID to probe: "))
print(f"\nResale-data for {asset_id}:")
data = api.fetch_resale_data(asset_id)
print(json.dumps(data, indent=2))
print(f"\nOwned by user {user_id}?")
print(api.is_owned(user_id, asset_id))
api.close()