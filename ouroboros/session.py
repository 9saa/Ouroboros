"""Cookie loading and CSRF extraction."""

import base64
import json


def load_cookies(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def extract_csrf(cookies: list) -> str | None:
    """The rbxcsrf4 cookie is a JWT whose payload contains the CSRF token."""
    for c in cookies:
        if c.get("name") == "rbxcsrf4":
            value = c.get("value", "")
            parts = value.split(".")
            if len(parts) < 2:
                return None
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            try:
                decoded = base64.urlsafe_b64decode(payload).decode("utf-8")
                return json.loads(decoded).get("csrf")
            except Exception:
                return None
    return None