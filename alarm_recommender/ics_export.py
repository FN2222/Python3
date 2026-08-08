"""导出 iPhone 可导入的日历 ICS（用于基于日期的闹钟/提醒）。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Union
from uuid import uuid4
from zoneinfo import ZoneInfo

from .recommender import AlarmRecommendation


DEFAULT_TZ = "Asia/Shanghai"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _dt_local(d: date, t: time, tz_name: str) -> str:
    """格式化为带时区偏移的本地时间，便于 iPhone 日历正确解析。"""
    tz = ZoneInfo(tz_name)
    dt = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)
    return dt.strftime("%Y%m%dT%H%M%S")


def _fold(line: str, limit: int = 75) -> List[str]:
    """RFC 5545 行折叠。"""
    if len(line) <= limit:
        return [line]
    parts = [line[:limit]]
    rest = line[limit:]
    while rest:
        parts.append(" " + rest[: limit - 1])
        rest = rest[limit - 1 :]
    return parts


def recommendation_to_vevent(
    rec: AlarmRecommendation,
    tz_name: str = DEFAULT_TZ,
    duration_minutes: int = 5,
    alarm_minutes_before: int = 0,
) -> Optional[str]:
    if not rec.should_alarm or rec.alarm_time is None:
        return None

    uid = f"{uuid4()}@iphone-date-alarm"
    start = _dt_local(rec.date, rec.alarm_time, tz_name)
    end_dt = (
        datetime.combine(rec.date, rec.alarm_time) + timedelta(minutes=duration_minutes)
    ).time()
    end = _dt_local(rec.date, end_dt, tz_name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    summary = _escape(rec.label)
    description = _escape(f"{rec.reason}\n{rec.tip}")
    categories = "ALARM,起床"

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID={tz_name}:{start}",
        f"DTEND;TZID={tz_name}:{end}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        f"CATEGORIES:{categories}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{summary}",
        f"TRIGGER:-PT{alarm_minutes_before}M" if alarm_minutes_before else "TRIGGER:PT0S",
        "END:VALARM",
        "END:VEVENT",
    ]
    return "\r\n".join(lines)


def build_ics(
    recommendations: Iterable[AlarmRecommendation],
    calendar_name: str = "日期闹钟推荐",
    tz_name: str = DEFAULT_TZ,
) -> str:
    events: List[str] = []
    for rec in recommendations:
        vevent = recommendation_to_vevent(rec, tz_name=tz_name)
        if vevent:
            events.append(vevent)

    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FN2222//iPhone Date Alarm Recommender//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        f"X-WR-TIMEZONE:{tz_name}",
    ]
    footer = ["END:VCALENDAR", ""]

    raw_lines: List[str] = []
    for block in header + events + footer:
        for line in block.split("\r\n"):
            raw_lines.extend(_fold(line))

    return "\r\n".join(raw_lines)


def write_ics(
    path: Union[Path, str],
    recommendations: Iterable[AlarmRecommendation],
    **kwargs,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_ics(recommendations, **kwargs)
    path.write_text(content, encoding="utf-8")
    return path
