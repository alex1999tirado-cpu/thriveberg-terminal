from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now(tz_name: str = "Europe/Madrid") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def is_business_day(day: date) -> bool:
    return day.weekday() < 5


def add_business_days(start: date, days: int) -> date:
    step = 1 if days >= 0 else -1
    remaining = abs(days)
    current = start
    while remaining:
        current += timedelta(days=step)
        if is_business_day(current):
            remaining -= 1
    return current


def add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(start.day, days_in_month[month - 1]))


def tenor_to_date(start: date, tenor: str) -> date:
    tenor = tenor.upper().strip()
    if tenor == "ON":
        return add_business_days(start, 1)
    if tenor == "TN":
        return add_business_days(start, 2)
    amount = int(tenor[:-1])
    unit = tenor[-1]
    if unit == "D":
        return add_business_days(start, amount)
    if unit == "W":
        return add_business_days(start, amount * 5)
    if unit == "M":
        return add_months(start, amount)
    if unit == "Y":
        return add_months(start, amount * 12)
    raise ValueError(f"Unsupported tenor: {tenor}")


def year_fraction(start: date, end: date, basis: str = "ACT/365") -> float:
    days = (end - start).days
    normalized = basis.upper().replace(" ", "")
    if normalized == "ACT/360":
        return days / 360.0
    if normalized == "ACT/365":
        return days / 365.0
    raise ValueError(f"Unsupported day count basis: {basis}")


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
