from __future__ import annotations

import time
from dataclasses import dataclass, field


class Clock:
    def sleep_ms(self, milliseconds: int) -> None:
        if milliseconds <= 0:
            return
        time.sleep(milliseconds / 1000.0)


@dataclass
class RecordingClock(Clock):
    """Records sleeps without necessarily waiting. Used by tests and dry runs."""

    sleeps: list[int] = field(default_factory=list)
    actually_sleep: bool = False

    def sleep_ms(self, milliseconds: int) -> None:
        self.sleeps.append(max(0, milliseconds))
        if self.actually_sleep and milliseconds > 0:
            time.sleep(milliseconds / 1000.0)
