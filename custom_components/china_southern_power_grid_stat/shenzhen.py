# Local review patch sz-review-1, 2026-10-18; see README.md and LICENSE.
"""Conservative parsing for Shenzhen calendar and bill responses.

No tariff calculation, I/O, or Home Assistant imports belong in this module.
Unknown response formats remain missing instead of becoming numeric zero.
"""

from __future__ import annotations

import datetime
import math
import re
from typing import Any


def optional_float(value: Any) -> float | None:
    """Read a finite number while retaining explicit zero and missing values."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def calendar_date(value: Any) -> datetime.date | None:
    """Accept complete calendar dates only; never infer a month from a day."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    for pattern, fmt in (
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"\d{4}/\d{2}/\d{2}", "%Y/%m/%d"),
        (r"\d{8}", "%Y%m%d"),
    ):
        if re.fullmatch(pattern, value):
            try:
                return datetime.datetime.strptime(value, fmt).date()
            except ValueError:
                return None
    return None


def parse_calendar_data(
    data: Any, year_month: tuple[int, int]
) -> tuple[float | None, list[dict[str, str | float]]]:
    """Keep the reported month total and valid, sorted daily measurements."""
    if not isinstance(data, dict):
        return None, []
    total = optional_float(data.get("totalPower"))
    rows = data.get("result")
    values: dict[datetime.date, float] = {}
    conflicts: set[datetime.date] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        date = calendar_date(row.get("date"))
        power = optional_float(row.get("power"))
        if date is None or (date.year, date.month) != year_month or power is None:
            continue
        if date in values and values[date] != power:
            conflicts.add(date)
        values[date] = power
    by_day = [
        {"date": date.isoformat(), "kwh": values[date]}
        for date in sorted(values)
        if date not in conflicts
    ]
    return total, by_day


def _bill_month(value: Any) -> tuple[int, int] | None:
    """Only accept an explicit YYYYMM or YYYY-MM month discriminator."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    match = re.fullmatch(r"(\d{4})-?(\d{2})", str(value).strip())
    if not match:
        return None
    year, month = map(int, match.groups())
    try:
        datetime.date(year, month, 1)
    except ValueError:
        return None
    return year, month


def select_month_bill(
    bills: Any,
    year_month: tuple[int, int],
    *,
    customer_id: str | None,
    account_number: str | None,
) -> dict | None:
    """Select one explicitly matching bill, keeping absent totals as None.

    Upstream has no response fixture proving the month field. An explicit
    yearMonth is therefore required; unknown formats fail closed until a
    redacted real response can establish its schema. Never use bills[0].
    """
    candidates = []
    for bill in bills if isinstance(bills, list) else []:
        if not isinstance(bill, dict) or _bill_month(bill.get("yearMonth")) != year_month:
            continue
        if any(
            bill.get(key) is not None
            and expected is not None
            and str(bill[key]) != str(expected)
            for key, expected in (
                ("eleCustId", customer_id),
                ("eleCustNumber", account_number),
            )
        ):
            continue
        candidates.append(bill)
    if len(candidates) != 1:
        return None
    selected = dict(candidates[0])
    selected["totalPower"] = optional_float(selected.get("totalPower"))
    selected["totalElectricity"] = optional_float(selected.get("totalElectricity"))
    return selected


def select_annual_month(
    by_month: Any, year_month: tuple[int, int]
) -> dict | None:
    """Use one explicit annual-detail month; never fill absent totals with zero."""
    if not isinstance(by_month, list):
        return None
    matches = [
        row
        for row in by_month
        if isinstance(row, dict) and _bill_month(row.get("month")) == year_month
    ]
    if len(matches) != 1:
        return None
    return {
        "totalPower": optional_float(matches[0].get("kwh")),
        "totalElectricity": optional_float(matches[0].get("charge")),
    }
