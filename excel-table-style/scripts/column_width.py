#!/usr/bin/env python3
"""Dependency-free column-width helpers for XLSX writers."""

from __future__ import annotations

import argparse
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable


def display_text(value: object, number_format: str | None = None) -> str:
    """Return the text Excel is expected to display for common table values."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        if number_format and "hh" in number_format.lower():
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float, Decimal)) and number_format and "," in number_format:
        decimals = 2 if ".00" in number_format else 0
        return f"{value:,.{decimals}f}"
    return str(value)


def display_width(value: object, number_format: str | None = None) -> int:
    """Measure the longest displayed line; CJK/full-width characters count as two."""
    text = display_text(value, number_format)
    return max(
        (
            sum(
                2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
                for char in line
            )
            for line in text.splitlines()
        ),
        default=0,
    )


def fitted_width(
    header: object,
    values: Iterable[object],
    *,
    number_format: str | None = None,
    font_size: float = 11,
    minimum: float = 10,
    maximum: float = 40,
) -> tuple[float, bool]:
    """Return (bounded width, wrap_text_required)."""
    header_width = display_width(header) + 2
    data_width = max(
        (display_width(value, number_format) + 1 for value in values),
        default=0,
    )
    raw_width = max(header_width, data_width) * (font_size / 11)
    return min(max(raw_width, minimum), maximum), raw_width > maximum


def recommended_zoom(font_size: float) -> int | None:
    """Return the explicit table zoom for supported font sizes."""
    if font_size == 10:
        return 240
    if font_size == 18:
        return 115
    return None


def self_test() -> None:
    assert display_width("ABC") == 3
    assert display_width("中文") == 4
    assert display_width(date(2026, 8, 26), "yyyy-mm-dd") == 10
    assert display_width(12345, "#,##0") == 6
    assert fitted_width("日期", [date(2026, 8, 26)])[0] == 11
    assert fitted_width("日期", [date(2026, 8, 26)], font_size=18)[0] == 18
    assert fitted_width("備註", ["中" * 30]) == (40, True)
    assert fitted_width("說明", ["short\n較長內容"])[0] == 10
    assert recommended_zoom(10) == 240
    assert recommended_zoom(18) == 115
    assert recommended_zoom(11) is None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("column-width self-test: PASS")


if __name__ == "__main__":
    main()
