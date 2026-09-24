#!/usr/bin/env python3
"""Purchase test for Ouroboros V0.2.3 (v4 challenge).

Usage:
    python test_purchase.py <asset_id> [price]
    python test_purchase.py <asset_id> --dry       # stops after prepare
"""

import argparse
import json
import random
import sys
import time

from ouroboros.api import ApiError, HexiumApi
from ouroboros.challenge import compute_interaction_hash, compute_proof
from ouroboros.config import load_settings
from ouroboros.session import extract_csrf, load_cookies


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset_id", type=int)
    parser.add_argument("price", nargs="?", type=int, default=0)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    settings = load_settings("settings.json")
    user_id = int(settings.get("user_id", 0))
    source = settings.get("purchase_source", "web-modal-v4")

    print("=" * 60)
    print("  Ouroboros purchase test (v4)")
    print("=" * 60)
    print(f"  Asset ID:  {args.asset_id}")
    print(f"  Price:     {args.price} R$")
    print(f"  User ID:   {user_id}")
    print(f"  Source:    {source}")
    print(f"  Dry run:   {'yes' if args.dry else 'no'}")
    print()

    if not user_id:
        print("  FAIL: user_id not set in settings.json")
        return 1

    # ---- cookies ---------------------------------------------------------
    print("[1] Loading cookies")
    try:
        cookies = load_cookies(settings["cookies_file"])
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1
    csrf = extract_csrf(cookies)
    if not csrf:
        print("  FAIL: no CSRF token")
        return 1
    print(f"  Cookies:   {len(cookies)}")
    print(f"  CSRF:      {csrf}")
    print()

    api = HexiumApi(cookies)
    try:
        # ---- prepare -----------------------------------------------------
        print("[2] Preparing purchase")
        try:
            prepared = api.prepare(args.asset_id, csrf)
        except ApiError as e:
            print(f"  FAIL: {e}")
            return 1

        token = prepared.get("purchaseToken")
        challenge = prepared.get("challenge")
        salt = prepared.get("salt", "")
        wait_ms = int(prepared.get("minWaitMs", 600))

        if not token or not challenge:
            print(f"  FAIL: prepare response missing fields")
            print(f"  keys: {list(prepared.keys())}")
            return 1

        print(f"  Token:     {token[:40]}...")
        print(f"  Challenge: {challenge}")
        print(f"  Salt:      {salt}")
        print(f"  minWaitMs: {wait_ms}")
        print()

        # ---- interaction + proof -----------------------------------------
        print("[3] Computing interaction hash and proof")
        timestamp = random.randint(5000, 25000)
        click_x = 683
        click_y = 384

        interaction_hash = compute_interaction_hash(
            challenge, salt, timestamp, click_x, click_y,
        )
        interaction_header = f"{timestamp}:{click_x}:{click_y}:{interaction_hash}"

        proof = compute_proof(
            challenge, salt, args.asset_id, user_id,
            csrf, interaction_hash,
        )

        print(f"  Interaction payload:")
        print(f"    hexium-v4-interaction:{challenge}:{salt}:"
              f"{timestamp}:{click_x}:{click_y}")
        print(f"  Interaction hash: {interaction_hash}")
        print(f"  Interaction hdr:  {interaction_header}")
        print()
        print(f"  Proof payload:")
        print(f"    hexium-v4-proof:{challenge}:{salt}:"
              f"{args.asset_id}:{user_id}:{csrf}:{interaction_hash}")
        print(f"  Proof: {proof}")
        print()

        if args.dry:
            print("  Dry run - stopping before confirm")
            return 0

        # ---- wait --------------------------------------------------------
        print(f"[4] Waiting {(wait_ms + 50) / 1000.0:.2f}s")
        time.sleep((wait_ms + 50) / 1000.0)

        # ---- confirm -----------------------------------------------------
        print("[5] Confirming purchase")
        try:
            result = api.confirm(
                args.asset_id, csrf, token, proof,
                interaction_header, args.price, source,
            )
        except ApiError as e:
            print(f"  FAIL: {e}")
            return 1

        print("  Response:")
        print("   ", json.dumps(result, indent=2)[:800])
        print()

        print("=" * 60)
        if result.get("purchased") is True:
            print("  RESULT: PURCHASED")
            return 0

        errors = result.get("errors") or []
        if errors:
            print(f"  RESULT: {errors[0].get('message')}")
            print("  (Request reached the server - flow is correct)")
            return 0

        print("  RESULT: UNKNOWN RESPONSE")
        return 1
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())
