"""命令行入口：苹果手机基于日期的闹钟推荐。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import __version__
from .holidays_cn import SUPPORTED_YEARS, get_day_info, holiday_summary
from .ics_export import write_ics
from .recommender import format_recommendation, recommend_alarm, recommend_range


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期格式无效: {value!r}，请使用 YYYY-MM-DD"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alarm-recommender",
        description=(
            "苹果手机基于日期的闹钟推荐：按中国法定节假日/调休判断是否该响铃，"
            "并导出 iPhone 日历可导入的 ICS。"
        ),
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # recommend
    p_rec = sub.add_parser("recommend", help="推荐某日或日期区间的闹钟")
    p_rec.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="目标日期 YYYY-MM-DD（默认今天）",
    )
    p_rec.add_argument(
        "--start",
        type=_parse_date,
        default=None,
        help="区间开始日期",
    )
    p_rec.add_argument(
        "--end",
        type=_parse_date,
        default=None,
        help="区间结束日期",
    )
    p_rec.add_argument(
        "--days",
        type=int,
        default=None,
        help="从 --date/--start 起连续 N 天（含当天）",
    )
    p_rec.add_argument(
        "--workday-time",
        default="07:00",
        help="工作日闹钟时间，默认 07:00",
    )
    p_rec.add_argument(
        "--weekend-time",
        default="09:00",
        help="周末闹钟时间；传 none 表示周末不设闹钟",
    )
    p_rec.add_argument(
        "--holiday-alarm",
        action="store_true",
        help="法定节假日也设置闹钟（使用周末时间）",
    )
    p_rec.add_argument(
        "--label",
        default="起床",
        help="闹钟名称前缀",
    )
    p_rec.add_argument(
        "--only-alarms",
        action="store_true",
        help="只输出需要开闹钟的日期",
    )
    p_rec.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出",
    )
    p_rec.add_argument(
        "--ics",
        type=Path,
        default=None,
        help="导出 ICS 文件路径（可导入 iPhone 日历）",
    )

    # day
    p_day = sub.add_parser("day", help="查询某日是工作日还是休息日")
    p_day.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="目标日期，默认今天",
    )

    # holidays
    p_hol = sub.add_parser("holidays", help="查看内置法定节假日安排")
    p_hol.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help=f"年份（已内置: {', '.join(map(str, SUPPORTED_YEARS))}）",
    )

    # guide
    sub.add_parser("guide", help="打印 iPhone 使用指南")

    return parser


def _weekend_time_arg(value: str) -> Optional[str]:
    if value.lower() in {"none", "off", "false", "-"}:
        return None
    return value


IPHONE_GUIDE = """
═══════════════════════════════════════════════════════════
  苹果手机：基于日期的闹钟怎么用
═══════════════════════════════════════════════════════════

问题
  iPhone「时钟」App 的闹钟只能按星期重复，不能指定「某年某月某日」。
  法定节假日/调休上班时，工作日闹钟容易误响或漏响。

本工具做什么
  1. 按国务院放假安排，判断每一天是否该开闹钟、几点响。
  2. 导出 ICS 日历文件 → 导入 iPhone「日历」→ 获得基于日期的提醒。
  3. 可选：用「快捷指令」把当天日历事件转成真正的时钟闹钟。

── 步骤 A：生成并导入 ICS ───────────────────────────────
  1. 在电脑上运行：
       python3 -m alarm_recommender recommend --days 30 --ics output/alarms.ics
  2. 把 alarms.ics 发到 iPhone（隔空投送 / 邮件 / 文件 App）。
  3. 在 iPhone 上打开该文件 →「添加到日历」→ 选择或新建日历
     （建议单独建一个「日期闹钟」日历）。

── 步骤 B（推荐）：快捷指令转时钟闹钟 ───────────────────
  时钟闹钟比日历提醒更响、更难被忽略。做法：
  1. 打开「快捷指令」→ 自动化 → 创建个人自动化 → 「一天中的时间」
     （例如每天 00:05）→ 立即执行。
  2. 动作大致为：
       · 查找日历事件（日历 = 「日期闹钟」，开始日期 是 今天）
       · 重复每一项：
           · 创建闹钟（时间 = 事件开始时间，标签 = 事件标题）
  3. 这样超过 24 小时以外的「日期闹钟」也会在当天自动落到时钟里。

── 步骤 C：节假日自动开关已有闹钟 ───────────────────────
  若你已有「每天 7:00」的工作日闹钟：
  1. 订阅或导入带「休/班」字样的节假日日历。
  2. 快捷指令每天凌晨：若今天日历含「休」→ 关闭该闹钟；
     含「班」或工作日 → 打开该闹钟。

── 常用命令 ─────────────────────────────────────────────
  # 今天推荐
  python3 -m alarm_recommender recommend

  # 查看未来 14 天
  python3 -m alarm_recommender recommend --days 14

  # 指定区间并导出 ICS
  python3 -m alarm_recommender recommend \\
    --start 2026-09-20 --end 2026-10-10 \\
    --workday-time 06:50 --weekend-time none \\
    --ics output/national-day.ics

  # 查某一天
  python3 -m alarm_recommender day --date 2026-10-01

  # 看全年放假
  python3 -m alarm_recommender holidays --year 2026
""".strip()


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "guide":
        print(IPHONE_GUIDE)
        return 0

    if args.command == "holidays":
        lines = holiday_summary(args.year)
        print(f"【{args.year} 年法定节假日】")
        for line in lines:
            print(f"  · {line}")
        return 0

    if args.command == "day":
        d = args.date or date.today()
        info = get_day_info(d)
        print(
            f"{info.date.isoformat()} {info.weekday_cn}  "
            f"{info.kind.value} / {info.name}"
        )
        return 0

    if args.command == "recommend":
        weekend_time = _weekend_time_arg(args.weekend_time)
        start = args.start or args.date or date.today()
        if args.end is not None:
            end = args.end
        elif args.days is not None:
            if args.days < 1:
                parser.error("--days 至少为 1")
            end = start + timedelta(days=args.days - 1)
        elif args.start is not None and args.date is None:
            end = start
        else:
            end = start

        recs = recommend_range(
            start,
            end,
            workday_time=args.workday_time,
            weekend_time=weekend_time,
            holiday_alarm=args.holiday_alarm,
            label=args.label,
            only_alarms=args.only_alarms,
        )

        if args.ics:
            path = write_ics(args.ics, recs)
            print(f"已导出 ICS：{path.resolve()}", file=sys.stderr)

        if args.json:
            print(json.dumps([r.to_dict() for r in recs], ensure_ascii=False, indent=2))
        else:
            if not recs:
                print("没有符合条件的推荐。")
            for r in recs:
                print(format_recommendation(r))
        return 0

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
