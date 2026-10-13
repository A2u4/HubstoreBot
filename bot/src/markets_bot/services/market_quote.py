"""Price quotes for in-game money ("valor IC") based on the Dinero store's USD price per million."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_MILLIONS = 1_000_000
_VALUE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([KM])$")


@dataclass(frozen=True, slots=True)
class IcValue:
    original: str
    amount: float
    unit: str
    millions: float


@dataclass(frozen=True, slots=True)
class Quote:
    millions: float
    base_price_per_million: float
    discount_per_million: float
    quote_price_per_million: float
    reference_price: float
    final_price: float
    reduction: float


def parse_ic_value(value: str) -> IcValue | None:
    """``450K`` / ``2.5M`` / ``120,5M`` -> parsed value, or None."""
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    match = _VALUE_RE.match(normalized)
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    if amount <= 0:
        return None
    unit = match.group(2)
    millions = amount / 1000 if unit == "K" else amount
    if not 0 < millions <= MAX_MILLIONS:
        return None
    return IcValue(normalized, amount, unit, millions)


def discount_for(millions: float) -> float:
    for limit, discount in ((1, 0.40), (5, 0.45), (20, 0.55), (40, 0.65), (60, 0.75), (80, 0.85), (100, 0.90)):
        if millions <= limit:
            return discount
    return 0.95


def calculate_quote(millions: float, base_price_per_million: float) -> Quote:
    if millions <= 0:
        raise ValueError("INVALID_IC_VALUE")
    if base_price_per_million <= 0:
        raise ValueError("INVALID_MILLION_PRICE")
    discount = discount_for(millions)
    per_million = max(0.01, round((base_price_per_million - discount) * 100) / 100)
    reference = millions * base_price_per_million
    final = round(millions * per_million * 100) / 100
    return Quote(millions, base_price_per_million, discount, per_million, reference, final, reference - final)


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _usd_amount(value: str) -> float | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if re.search(r"\bUSDT\b", text, re.IGNORECASE):
        return None
    before = re.search(r"(?:^|[^\d])([0-9]+(?:[.,][0-9]+)?)\s*USD\b", text, re.IGNORECASE)
    after = re.search(r"\bUSD\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)", text, re.IGNORECASE)
    raw = (before or after).group(1) if (before or after) else None
    if raw is None:
        return None
    amount = float(raw.replace(",", "."))
    return amount if amount > 0 else None


def extract_usd_million_price(shop_categories: Any) -> float | None:
    """USD price per million from the "Dinero" store (United States first, else any USD price)."""
    if not isinstance(shop_categories, list):
        return None
    money = next((c for c in shop_categories if isinstance(c, dict) and (
        str(c.get("id") or "").lower() == "dinero" or _norm(str(c.get("label") or "")) == "dinero")), None)
    options = money.get("paymentOptions") if isinstance(money, dict) else None
    options = options if isinstance(options, list) else []
    preferred = next((o for o in options if isinstance(o, dict)
                      and _norm(str(o.get("country") or "")) in ("estados unidos", "united states")
                      and _usd_amount(str(o.get("price") or "")) is not None), None)
    fallback = next((o for o in options if isinstance(o, dict) and _usd_amount(str(o.get("price") or "")) is not None), None)
    chosen = preferred or fallback
    return _usd_amount(str(chosen.get("price") or "")) if chosen else None


def format_decimal(value: float, decimals: int = 3) -> str:
    """``1234.5`` -> ``1,234.5`` (en-US grouping, trailing zeros removed)."""
    text = f"{value:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
