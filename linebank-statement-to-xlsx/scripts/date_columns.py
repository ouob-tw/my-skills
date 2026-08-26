"""Normalize LINE Bank card dates without inventing missing posting dates."""

import re
from datetime import date

FULL_DATE_PATTERN = r"\d{4}[./-]\d{1,2}[./-]\d{1,2}"


def _canonical_headers(headers: list[str]) -> tuple[list[str], list[str]]:
    normalized = [re.sub(r"\s+", "", header) for header in headers]
    canonical = [
        value if value in {"消費日", "入帳日", "換匯日"} else header
        for header, value in zip(headers, normalized)
    ]
    return normalized, canonical


def _split_date_pair(value) -> tuple[str, str]:
    text = str(value).strip()
    compact = re.fullmatch(
        rf"({FULL_DATE_PATTERN})\s*/\s*({FULL_DATE_PATTERN})",
        text,
    )
    if compact:
        return compact.group(1), compact.group(2)
    spaced = re.split(r"\s+/\s+", text, maxsplit=1)
    return spaced[0], spaced[1] if len(spaced) == 2 else ""


def separate_card_dates(headers: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    normalized, canonical = _canonical_headers(headers)
    if "消費日" in normalized and "入帳日" in normalized:
        return canonical, rows

    if "消費日/入帳日" in normalized:
        date_index = normalized.index("消費日/入帳日")
    elif "日期" in normalized:
        date_index = normalized.index("日期")
    elif "消費日" in normalized:
        date_index = normalized.index("消費日")
    else:
        raise ValueError("刷卡記錄缺少消費日欄位")

    separated_headers = (
        headers[:date_index] + ["消費日", "入帳日"] + headers[date_index + 1:]
    )
    separated_rows = []
    for row in rows:
        consumption_date, posting_date = _split_date_pair(row[date_index])
        separated_rows.append(
            row[:date_index]
            + [consumption_date, posting_date]
            + row[date_index + 1:]
        )
    return separated_headers, separated_rows


def separate_exchange_date(headers: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    normalized, canonical = _canonical_headers(headers)
    if "外幣消費金額/換匯日" not in normalized:
        return canonical, rows

    index = normalized.index("外幣消費金額/換匯日")
    separated_headers = headers[:index] + ["外幣消費金額", "換匯日"] + headers[index + 1 :]
    separated_rows = []
    for row in rows:
        text = str(row[index]).strip()
        parts = re.fullmatch(rf"(.*?)\s*/\s*({FULL_DATE_PATTERN})", text)
        amount = parts.group(1) if parts else text
        exchange_date = parts.group(2) if parts else ""
        separated_rows.append(row[:index] + [amount, exchange_date] + row[index + 1 :])
    return separated_headers, separated_rows


def parse_statement_date(value, statement_year: int, statement_month: int) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    full = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if full:
        return date(*(int(part) for part in full.groups()))
    short = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if not short:
        raise ValueError(f"無法解析日期：{value!r}")
    month, day = (int(part) for part in short.groups())
    year = statement_year - 1 if month > statement_month + 1 else statement_year
    return date(year, month, day)


def normalize_date_columns(
    headers: list[str], rows: list[list], statement_year: int, statement_month: int
) -> list[list]:
    date_indexes = [
        index
        for index, header in enumerate(headers)
        if re.sub(r"\s+", "", header) in {"消費日", "入帳日", "換匯日"}
    ]
    normalized_rows = []
    for row in rows:
        normalized = list(row)
        for index in date_indexes:
            normalized[index] = parse_statement_date(
                normalized[index], statement_year, statement_month
            )
        normalized_rows.append(normalized)
    return normalized_rows
