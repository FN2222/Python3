"""Sequential, human-paced course reader.

Reads like a student: one lesson page at a time, including figures /
topology diagrams, then saves notes before opening the next page.
Stops on login walls, captchas, 403/429 — never bypasses them.
"""

from .config import ReaderConfig
from .models import AccessStopped, ReadEvent, ReadEventKind, StopReason
from .session import CourseReadSession, HumanReadSession

__all__ = [
    "AccessStopped",
    "CourseReadSession",
    "HumanReadSession",
    "ReadEvent",
    "ReadEventKind",
    "ReaderConfig",
    "StopReason",
]

__version__ = "0.2.0"
