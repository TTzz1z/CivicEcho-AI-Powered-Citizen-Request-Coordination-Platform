from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class NormalizedTime:
    start: datetime
    end: datetime
    precision: str
    timezone: str


def _day_bounds(day, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, zone)
    return start, start + timedelta(days=1)


def normalize_chinese_time(text: str | None, timezone_name: str, now: datetime | None = None) -> NormalizedTime | None:
    """Conservative parser for the verified expressions not already normalized by Duckling."""
    if not text:
        return None
    zone = ZoneInfo(timezone_name)
    reference = (now or datetime.now(zone)).astimezone(zone)
    value = text.strip()
    if value == "昨天晚上":
        day = reference.date() - timedelta(days=1)
        start = datetime.combine(day, time(18, 0), zone)
        return NormalizedTime(start, start + timedelta(hours=6), "part_of_day", timezone_name)
    match = re.fullmatch(r"([一二两三四五六七八九十\d]+)天前", value)
    if match:
        raw = match.group(1)
        numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        days = int(raw) if raw.isdigit() else numbers.get(raw)
        if days is not None:
            start, end = _day_bounds(reference.date() - timedelta(days=days), zone)
            return NormalizedTime(start, end, "day", timezone_name)
    if value == "上周一":
        this_monday = reference.date() - timedelta(days=reference.weekday())
        start, end = _day_bounds(this_monday - timedelta(days=7), zone)
        return NormalizedTime(start, end, "day", timezone_name)
    if value == "最近一个月":
        year, month = reference.year, reference.month - 1
        if month == 0:
            year, month = year - 1, 12
        day = min(reference.day, monthrange(year, month)[1])
        start = reference.replace(year=year, month=month, day=day)
        return NormalizedTime(start, reference, "range", timezone_name)
    return None
