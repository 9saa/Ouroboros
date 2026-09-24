"""Shared coordinator: prevents two modules from buying the same item."""

import threading


_purchasing: set[int] = set()
_lock = threading.Lock()


def claim(asset_id: int) -> bool:
    """Try to claim an asset for purchase.

    Returns True if we got the claim, False if another module already has it.
    """
    with _lock:
        if asset_id in _purchasing:
            return False
        _purchasing.add(asset_id)
        return True


def release(asset_id: int) -> None:
    with _lock:
        _purchasing.discard(asset_id)