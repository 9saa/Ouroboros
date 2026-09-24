"""Session watch module: periodically reports cookie age."""

from ouroboros.log import Logger
from ouroboros.modules import Module
from ouroboros.session import load_cookies, session_report


class SessionWatch(Module):
    name = "SessionWatch"

    def __init__(self, settings: dict) -> None:
        super().__init__(settings)
        self.log = Logger("SessionWatch")

    def run(self) -> None:
        self.log.info("Starting up")
        interval = 3600.0  # once an hour

        while not self.should_stop():
            try:
                cookies = load_cookies(self.settings["cookies_file"])
                report = session_report(cookies)
                for name, age in report:
                    if age is None:
                        self.log.info(f"{name}: unknown age")
                    else:
                        warn = "  <- expired soon" if age > 27 else ""
                        self.log.info(f"{name}: {age:.1f} days old{warn}")
            except Exception as e:
                self.log.warn(f"Could not check: {e}")

            self.sleep(interval)

        self.log.info("Stopped")