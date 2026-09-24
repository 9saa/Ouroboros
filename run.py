#!/usr/bin/env python3
"""Ouroboros V0.2.1 - Hexium sniper + restock watcher."""

import sys
import time

from ouroboros import __version__
from ouroboros.banner import print_header
from ouroboros.config import load_settings
from ouroboros.log import Logger, set_level
from ouroboros.modules import Manager
from ouroboros.restock import Restock
from ouroboros.sniper import Sniper


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    settings = load_settings("settings.json")
    set_level(settings.get("log_level", "INFO"))

    modules = [
        Sniper(settings),
        Restock(settings),
    ]

    manager = Manager()
    for m in modules:
        manager.register(m)

    print_header(modules)
    print()
    print("-" * 80)
    print()

    log = Logger("Ouroboros")
    log.info(f"Ouroboros v{__version__} - {len(modules)} module(s)")

    manager.start_all()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.warn("Interrupt received - stopping...")
    finally:
        manager.stop_all()
        log.info("Goodbye")

    return 0


if __name__ == "__main__":
    sys.exit(main())