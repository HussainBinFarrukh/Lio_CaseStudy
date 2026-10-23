"""Tolerant number parsing for values read from vendor quotes (US formats only)."""
import re

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def parse_amount(value: object) -> float | None:
    """Read an amount as printed on a quote: ``"$1,409.06"`` -> ``1409.06``.

    Returns ``None`` for missing or unreadable values instead of raising, so one
    bad value never discards the rest of an extraction.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    # Thousands separators and currency symbols/words carry no value.
    match = _NUMBER.search(text.replace(",", ""))
    if match is None:
        return None
    number = float(match.group())
    return -number if negative else number


def parse_percent(value: object) -> float | None:
    """Read a discount percentage: ``"-20.00%"`` -> ``20.0`` (sign-insensitive)."""
    number = parse_amount(value)
    return abs(number) if number is not None else None
