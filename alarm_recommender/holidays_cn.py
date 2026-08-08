"""中国法定节假日与调休上班日数据（国务院办公厅通知）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple


class DayKind(str, Enum):
    WORKDAY = "workday"  # 工作日（含调休上班）
    WEEKEND = "weekend"  # 普通周末
    HOLIDAY = "holiday"  # 法定放假/调休放假


@dataclass(frozen=True)
class DayInfo:
    date: date
    kind: DayKind
    name: str
    weekday_cn: str

    @property
    def is_workday(self) -> bool:
        return self.kind == DayKind.WORKDAY


WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _expand(ranges: List[Tuple[str, str, str]]) -> Dict[date, str]:
    """将 (start, end, name) 展开为日期 -> 名称。"""
    out: Dict[date, str] = {}
    for start_s, end_s, name in ranges:
        start = date.fromisoformat(start_s)
        end = date.fromisoformat(end_s)
        for d in _daterange(start, end):
            out[d] = name
    return out


# 放假日期（含调休放假）
_HOLIDAY_RANGES: Dict[int, List[Tuple[str, str, str]]] = {
    2025: [
        ("2025-01-01", "2025-01-01", "元旦"),
        ("2025-01-28", "2025-02-04", "春节"),
        ("2025-04-04", "2025-04-06", "清明节"),
        ("2025-05-01", "2025-05-05", "劳动节"),
        ("2025-05-31", "2025-06-02", "端午节"),
        ("2025-10-01", "2025-10-08", "国庆节/中秋节"),
    ],
    2026: [
        ("2026-01-01", "2026-01-03", "元旦"),
        ("2026-02-15", "2026-02-23", "春节"),
        ("2026-04-04", "2026-04-06", "清明节"),
        ("2026-05-01", "2026-05-05", "劳动节"),
        ("2026-06-19", "2026-06-21", "端午节"),
        ("2026-09-25", "2026-09-27", "中秋节"),
        ("2026-10-01", "2026-10-07", "国庆节"),
    ],
}

# 调休上班日
_WORK_OVERRIDES: Dict[int, Dict[date, str]] = {
    2025: {
        date(2025, 1, 26): "春节调休上班",
        date(2025, 2, 8): "春节调休上班",
        date(2025, 4, 27): "劳动节调休上班",
        date(2025, 9, 28): "国庆/中秋调休上班",
        date(2025, 10, 11): "国庆/中秋调休上班",
    },
    2026: {
        date(2026, 1, 4): "元旦调休上班",
        date(2026, 2, 14): "春节调休上班",
        date(2026, 2, 28): "春节调休上班",
        date(2026, 5, 9): "劳动节调休上班",
        date(2026, 9, 20): "国庆调休上班",
        date(2026, 10, 10): "国庆调休上班",
    },
}

_HOLIDAYS: Dict[date, str] = {}
for year, ranges in _HOLIDAY_RANGES.items():
    _HOLIDAYS.update(_expand(ranges))

_WORKDAYS: Dict[date, str] = {}
for year, mapping in _WORK_OVERRIDES.items():
    _WORKDAYS.update(mapping)


SUPPORTED_YEARS = sorted(_HOLIDAY_RANGES.keys())


def get_day_info(d: date) -> DayInfo:
    """返回某日的工作日/休息日信息。"""
    weekday_cn = WEEKDAY_CN[d.weekday()]

    if d in _WORKDAYS:
        return DayInfo(d, DayKind.WORKDAY, _WORKDAYS[d], weekday_cn)

    if d in _HOLIDAYS:
        return DayInfo(d, DayKind.HOLIDAY, f"{_HOLIDAYS[d]}(休)", weekday_cn)

    if d.weekday() >= 5:
        return DayInfo(d, DayKind.WEEKEND, "周末", weekday_cn)

    return DayInfo(d, DayKind.WORKDAY, "工作日", weekday_cn)


def holiday_summary(year: int) -> List[str]:
    """人类可读的年度放假摘要。"""
    if year not in _HOLIDAY_RANGES:
        return [f"{year} 年放假数据尚未内置，仅按周末/工作日判断。"]

    lines: List[str] = []
    for start_s, end_s, name in _HOLIDAY_RANGES[year]:
        start = date.fromisoformat(start_s)
        end = date.fromisoformat(end_s)
        days = (end - start).days + 1
        if start == end:
            lines.append(f"{name}：{start_s}，共 {days} 天")
        else:
            lines.append(f"{name}：{start_s} 至 {end_s}，共 {days} 天")

    work = _WORK_OVERRIDES.get(year, {})
    if work:
        work_str = "、".join(sorted(d.isoformat() for d in work))
        lines.append(f"调休上班：{work_str}")
    return lines


def supported_year(d: Optional[date] = None) -> bool:
    target = (d or date.today()).year
    return target in _HOLIDAY_RANGES
