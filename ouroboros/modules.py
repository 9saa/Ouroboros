"""Module framework: base class + manager."""

import threading
from enum import Enum

from ouroboros.log import Logger


class State(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class Module:
    name = "module"

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.state = State.CREATED
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self.state = State.RUNNING
        self._thread = threading.Thread(
            target=self._run_wrapper, name=self.name, daemon=True,
        )
        self._thread.start()

    def _run_wrapper(self) -> None:
        log = Logger("Manager")
        try:
            self.run()
        except Exception as e:
            log.error(f"{self.name} crashed: {e}")
            self.state = State.FAILED
        else:
            self.state = State.STOPPED

    def run(self) -> None:
        raise NotImplementedError

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def sleep(self, seconds: float) -> None:
        deadline = threading.Event()
        while not self._stop.is_set():
            if deadline.wait(timeout=min(seconds, 0.2)):
                return
            seconds -= 0.2
            if seconds <= 0:
                return

    def status_line(self) -> str:
        return self.state.value.upper()


class Manager:
    def __init__(self) -> None:
        self.modules: list[Module] = []

    def register(self, module: Module) -> None:
        self.modules.append(module)

    def start_all(self) -> None:
        for m in self.modules:
            try:
                m.start()
            except Exception as e:
                Logger("Manager").error(f"Failed to start {m.name}: {e}")

    def stop_all(self) -> None:
        for m in self.modules:
            try:
                m.stop()
            except Exception:
                pass

    def snapshot(self) -> list:
        return [(m.name, m.state.value) for m in self.modules]