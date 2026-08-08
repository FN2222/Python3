"""单元测试：节假日判断与闹钟推荐。"""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
import tempfile

from alarm_recommender.holidays_cn import DayKind, get_day_info
from alarm_recommender.ics_export import build_ics, write_ics
from alarm_recommender.recommender import recommend_alarm, recommend_range


class HolidayTests(unittest.TestCase):
    def test_2026_national_day_holiday(self):
        info = get_day_info(date(2026, 10, 1))
        self.assertEqual(info.kind, DayKind.HOLIDAY)
        self.assertIn("国庆", info.name)

    def test_2026_makeup_workday(self):
        info = get_day_info(date(2026, 9, 20))  # 周日但调休上班
        self.assertEqual(info.kind, DayKind.WORKDAY)
        self.assertIn("调休", info.name)

    def test_normal_weekend(self):
        info = get_day_info(date(2026, 8, 9))  # 周日，非节假日
        self.assertEqual(info.kind, DayKind.WEEKEND)

    def test_normal_workday(self):
        info = get_day_info(date(2026, 8, 10))  # 周一
        self.assertEqual(info.kind, DayKind.WORKDAY)
        self.assertEqual(info.name, "工作日")

    def test_2025_spring_festival(self):
        info = get_day_info(date(2025, 1, 28))
        self.assertEqual(info.kind, DayKind.HOLIDAY)


class RecommendTests(unittest.TestCase):
    def test_workday_alarm_on(self):
        rec = recommend_alarm(date(2026, 8, 10), workday_time="06:45")
        self.assertTrue(rec.should_alarm)
        self.assertEqual(rec.alarm_time.strftime("%H:%M"), "06:45")

    def test_holiday_alarm_off(self):
        rec = recommend_alarm(date(2026, 10, 1))
        self.assertFalse(rec.should_alarm)
        self.assertIsNone(rec.alarm_time)

    def test_makeup_sunday_alarm_on(self):
        rec = recommend_alarm(date(2026, 10, 10))  # 周六调休上班
        self.assertTrue(rec.should_alarm)
        self.assertEqual(rec.day_info.kind, DayKind.WORKDAY)

    def test_weekend_none(self):
        rec = recommend_alarm(date(2026, 8, 9), weekend_time=None)
        self.assertFalse(rec.should_alarm)

    def test_range_only_alarms(self):
        recs = recommend_range(
            date(2026, 10, 1),
            date(2026, 10, 10),
            weekend_time=None,
            only_alarms=True,
        )
        # 10/1-7 放假，10/8-9 正常工作日? 10/8 周四工作日, 10/9 周五工作日, 10/10 调休上班
        # 10/1-7 holiday off, so alarms: 10/8, 10/9, 10/10
        dates = [r.date for r in recs]
        self.assertEqual(dates, [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10)])


class IcsTests(unittest.TestCase):
    def test_build_ics_contains_event(self):
        recs = recommend_range(date(2026, 8, 10), date(2026, 8, 10))
        ics = build_ics(recs)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("BEGIN:VALARM", ics)
        self.assertIn("SUMMARY:", ics)

    def test_write_ics_skips_off_days(self):
        recs = recommend_range(date(2026, 10, 1), date(2026, 10, 1))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_ics(Path(tmp) / "a.ics", recs)
            content = path.read_text(encoding="utf-8")
            self.assertIn("BEGIN:VCALENDAR", content)
            self.assertNotIn("BEGIN:VEVENT", content)


if __name__ == "__main__":
    unittest.main()
