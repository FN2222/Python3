"""iPhone 基于日期的闹钟推荐工具。"""

__version__ = "1.0.0"

from .recommender import AlarmRecommendation, recommend_alarm, recommend_range

__all__ = [
    "AlarmRecommendation",
    "recommend_alarm",
    "recommend_range",
    "__version__",
]
