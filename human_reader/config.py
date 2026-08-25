from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_VIEWPORT_CHARS = 720
DEFAULT_CJK_CHARS_PER_MINUTE = 420
DEFAULT_WORD_PER_MINUTE = 230


@dataclass(frozen=True)
class ReaderConfig:
    """Pacing knobs. Defaults mimic a careful student, not a burst fetcher."""

    viewport_chars: int = DEFAULT_VIEWPORT_CHARS
    scroll_overlap: float = 0.18
    cjk_chars_per_minute: float = DEFAULT_CJK_CHARS_PER_MINUTE
    words_per_minute: float = DEFAULT_WORD_PER_MINUTE
    timing_jitter: float = 0.22
    reread_probability: float = 0.09
    pause_probability: float = 0.14
    idle_probability: float = 0.035
    min_scroll_ms: int = 320
    max_scroll_ms: int = 1200
    settle_ms_min: int = 650
    settle_ms_max: int = 2100
    pause_ms_min: int = 400
    pause_ms_max: int = 2600
    idle_ms_min: int = 2500
    idle_ms_max: int = 8000
    inter_page_ms_min: int = 2200
    inter_page_ms_max: int = 7500
    diagram_ms_min: int = 1800
    diagram_ms_max: int = 9000
    notes_ms_min: int = 900
    notes_ms_max: int = 3200
    asset_gap_ms_min: int = 350
    asset_gap_ms_max: int = 1100
    fatigue_per_viewport: float = 0.025
    speed: float = 1.0
    seed: int | None = None
    max_pages: int = 80
    max_assets_per_page: int = 40
    check_robots: bool = True
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    request_timeout_s: int = 25
    viewport_px: int = 820
    cookies_path: str | None = None
    storage_state_path: str | None = None
    save_dir: str | None = None
    download_assets: bool = True

    def scaled_ms(self, milliseconds: int) -> int:
        if self.speed <= 0:
            return 0
        return max(0, int(round(milliseconds / self.speed)))

    def output_dir(self) -> Path | None:
        return Path(self.save_dir) if self.save_dir else None
