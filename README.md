# 苹果手机 · 基于日期的闹钟推荐

iPhone「时钟」闹钟只能按**星期**重复，不能指定「某年某月某日」。  
本工具用 Python 按**中国法定节假日 / 调休上班**生成每日闹钟建议，并导出可导入 iPhone 日历的 **ICS** 文件。

## 功能

- 判断工作日 / 周末 / 法定放假 / 调休上班
- 推荐是否开闹钟及时间（工作日、周末可分别设置）
- 导出 ICS，导入 iPhone「日历」获得**基于日期**的提醒
- 内置使用指南：如何用「快捷指令」转成真正的时钟闹钟

内置放假数据：**2025、2026**（国务院办公厅通知）。

## 快速开始

```bash
# 今天推荐
python3 -m alarm_recommender recommend

# 未来 14 天
python3 -m alarm_recommender recommend --days 14

# 导出 ICS（发给 iPhone 打开即可添加到日历）
python3 -m alarm_recommender recommend --days 30 --ics output/alarms.ics

# 国庆前后：周末不设闹钟，工作日 06:50
python3 -m alarm_recommender recommend \
  --start 2026-09-20 --end 2026-10-10 \
  --workday-time 06:50 --weekend-time none \
  --ics output/national-day.ics

# 查某一天 / 全年放假 / iPhone 用法
python3 -m alarm_recommender day --date 2026-10-01
python3 -m alarm_recommender holidays --year 2026
python3 -m alarm_recommender guide
```

## iPhone 怎么用

1. 运行命令生成 `alarms.ics`，隔空投送到 iPhone。
2. 打开文件 → **添加到日历**（建议单独建「日期闹钟」日历）。
3. （推荐）用「快捷指令」每天凌晨：查找今天该日历事件 → **创建闹钟**。  
   这样超过 24 小时的日期安排也会在当天落到时钟 App。

完整步骤见：`python3 -m alarm_recommender guide`

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 项目结构

```
alarm_recommender/
  holidays_cn.py   # 法定节假日与调休
  recommender.py   # 推荐逻辑
  ics_export.py    # ICS 导出
  cli.py           # 命令行
```
