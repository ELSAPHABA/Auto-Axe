"""Pure, canonical boundary values shared by future use cases."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Mode(StrEnum):
    BACKTEST = "BACKTEST"
    DRY_RUN = "DRY_RUN"
    PAPER_LOCAL = "PAPER_LOCAL"
    PAPER_BROKER = "PAPER_BROKER"
    LIVE = "LIVE"


def decimal_string(value: object) -> str:
    """Reject floats, invalid input, nonfinite values and excessive input lengths."""
    if not isinstance(value, (str, Decimal)) or len(str(value)) > 128:
        raise ValueError("money must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite() or abs(number.adjusted()) > 128:
        raise ValueError("invalid decimal range")
    if number == 0:
        return "0"
    # Avoid Decimal.normalize(): it rounds using the active context.
    result = format(number, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


def utc_string(value: datetime) -> str:
    return utc_datetime(value).isoformat().replace("+00:00", "Z")
