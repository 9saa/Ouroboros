"""Purchase proof functions for the v4 challenge system.

interaction_hash = sha256_hex("hexium-v4-interaction:" + challenge + ":" + salt
                              + ":" + timestamp + ":" + click_x + ":" + click_y)

proof = sha256_hex("hexium-v4-proof:" + challenge + ":" + salt + ":" + asset_id
                   + ":" + user_id + ":" + csrf + ":" + interaction_hash)
"""

import hashlib


INTERACTION_PREFIX = "hexium-v4-interaction:"
PROOF_PREFIX = "hexium-v4-proof:"


def compute_interaction_hash(
    challenge: str,
    salt: str,
    timestamp: int,
    click_x: int,
    click_y: int,
) -> str:
    payload = (
        f"{INTERACTION_PREFIX}"
        f"{challenge}:{salt or ''}:{timestamp}:{click_x}:{click_y}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_proof(
    challenge: str,
    salt: str,
    asset_id: int,
    user_id: int,
    csrf: str,
    interaction_hash: str,
) -> str:
    payload = (
        f"{PROOF_PREFIX}"
        f"{challenge}:{salt or ''}:{asset_id}:"
        f"{user_id or ''}:{csrf or ''}:{interaction_hash or ''}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
