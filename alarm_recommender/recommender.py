"""基于日期的闹钟推荐逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from .holidays_cn import DayInfo, DayKind, get_day_info


@dataclass(frozen=True)
class AlarmRecommendation:
    date: date
    day_info: DayInfo
    should_alarm: bool
    alarm_time: Optional[time]
    label: str
    reason: str
    tip: str

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "weekday": self.day_info.weekday_cn,
            "day_kind": self.day_info.kind.value,
            "day_name": self.day_info.name,
            "should_alarm": self.should_alarm,
            "alarm_time": self.alarm_time.strftime("%H:%M") if self.alarm_time else None,
            "label": self.label,
            "reason": self.reason,
            "tip": self.tip,
        }


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def recommend_alarm(
    target: date,
    workday_time: str = "07:00",
    weekend_time: Optional[str] = "09:00",
    holiday_alarm: bool = False,
    label: str = "起床",
) -> AlarmRecommendation:
    """
    根据日期类型推荐是否设置闹钟及时间。

    - 工作日 / 调休上班：推荐上班闹钟
    - 周末：默认推荐较晚闹钟（可关闭）
    - 法定节假日：默认不设闹钟（holiday_alarm=True 时可设）
    """
    info = get_day_info(target)
    work_t = _parse_time(workday_time)
    rest_t = _parse_time(weekend_time) if weekend_time else None

    if info.kind == DayKind.WORKDAY:
        reason = (
            f"{info.name}，建议设置工作日闹钟"
            if "调休" in info.name
            else "工作日，建议设置闹钟"
        )
        tip = (
            "苹果时钟闹钟不支持指定日期；可导入日历事件，"
            "再用「快捷指令」在当天自动创建闹钟。"
        )
        return AlarmRecommendation(
            date=target,
            day_info=info,
            should_alarm=True,
            alarm_time=work_t,
            label=f"{label}·工作日",
            reason=reason,
            tip=tip,
        )

    if info.kind == DayKind.HOLIDAY:
        if holiday_alarm and rest_t is not None:
            return AlarmRecommendation(
                date=target,
                day_info=info,
                should_alarm=True,
                alarm_time=rest_t,
                label=f"{label}·假期",
                reason=f"{info.name}，按你的设置仍推荐假期闹钟",
                tip="假期可把闹钟设晚一些，或仅用日历提醒。",
            )
        return AlarmRecommendation(
            date=target,
            day_info=info,
            should_alarm=False,
            alarm_time=None,
            label=f"{label}·关闭",
            reason=f"{info.name}，建议关闭起床闹钟",
            tip="可用快捷指令每天凌晨检查日历「休」字，自动关闭工作日闹钟。",
        )

    # 普通周末
    if rest_t is None:
        return AlarmRecommendation(
            date=target,
            day_info=info,
            should_alarm=False,
            alarm_time=None,
            label=f"{label}·关闭",
            reason="周末，建议关闭闹钟或睡到自然醒",
            tip="若需要周末闹钟，请传入 --weekend-time。",
        )

    return AlarmRecommendation(
        date=target,
        day_info=info,
        should_alarm=True,
        alarm_time=rest_t,
        label=f"{label}·周末",
        reason="周末，推荐较晚的闹钟",
        tip="导入 ICS 后，在 iPhone「日历」中可收到基于日期的提醒。",
    )


def recommend_range(
    start: date,
    end: date,
    workday_time: str = "07:00",
    weekend_time: Optional[str] = "09:00",
    holiday_alarm: bool = False,
    label: str = "起床",
    only_alarms: bool = False,
) -> List[AlarmRecommendation]:
    if end < start:
        raise ValueError("结束日期不能早于开始日期")

    results: List[AlarmRecommendation] = []
    cur = start
    while cur <= end:
        rec = recommend_alarm(
            cur,
            workday_time=workday_time,
            weekend_time=weekend_time,
            holiday_alarm=holiday_alarm,
            label=label,
        )
        if not only_alarms or rec.should_alarm:
            results.append(rec)
        cur += timedelta(days=1)
    return results


def format_recommendation(rec: AlarmRecommendation) -> str:
    status = "开" if rec.should_alarm else "关"
    time_s = rec.alarm_time.strftime("%H:%M") if rec.alarm_time else "--:--"
    return (
        f"{rec.date.isoformat()} {rec.day_info.weekday_cn} "
        f"[{rec.day_info.name}] 闹钟{status} {time_s}  "
        f"{rec.reason}"
    )
