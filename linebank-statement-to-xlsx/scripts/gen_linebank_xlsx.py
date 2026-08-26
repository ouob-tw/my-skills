"""Extract LINE Bank statement data from HTML and generate Excel.

Usage:
  uv run --with xlsxwriter --with beautifulsoup4 scripts/gen_linebank_xlsx.py <html_path> [output_dir]

Output: <output_dir>/YYYY-MM_交易明細.xlsx, or next to HTML when output_dir is omitted
Deps:   beautifulsoup4, xlsxwriter (injected by uv --with)
"""
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import xlsxwriter
from bs4 import BeautifulSoup
from date_columns import (
    normalize_date_columns,
    separate_card_dates,
    separate_exchange_date,
)

EMPTY_CARD_HEADERS = [
    "消費日",
    "入帳日",
    "交易說明",
    "新臺幣金額",
    "消費國家",
    "外幣消費金額",
    "換匯日",
    "支付帳戶帳號",
]
FONT_SIZE = 18

if len(sys.argv) not in (2, 3):
    print(f"Usage: {sys.argv[0]} <html_path> [output_dir]")
    sys.exit(1)

HTML = Path(sys.argv[1])
OUTPUT_DIR = Path(sys.argv[2]) if len(sys.argv) == 3 else HTML.parent
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def dispw(s):
    if isinstance(s, (date, datetime)):
        s = s.strftime("%Y-%m-%d")
    return max(
        (
            sum(
                2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1
                for c in line
            )
            for line in str(s or "").splitlines()
        ),
        default=0,
    )

def col_width(rows, idx):
    width = max((dispw(r[idx]) for r in rows if idx < len(r)), default=8) + 2
    width *= FONT_SIZE / 11
    return min(max(width, 10), 40)

def parse_amount(s):
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        return s

def get_table(soup, tab_id):
    tab = soup.find(id=tab_id)
    if not tab:
        return []
    rows = tab.find(class_="table-scroll").find_all("tr")
    return [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
            for r in rows if r.find_all(["th", "td"])]

def header_index(headers, *names):
    for name in names:
        if name in headers:
            return headers.index(name)
    raise ValueError(f"缺少必要欄位：{'、'.join(names)}")

def stated_amount(soup, tab_id, pattern):
    tab = soup.find(id=tab_id)
    if not tab:
        return None
    text = tab.find(class_="chart-section").get_text(" ", strip=True)
    m = re.search(pattern, text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))

def statement_year_month(soup, html_path):
    text = soup.get_text(" ", strip=True)
    match = re.search(r"對帳單期間\s*[:：]?\s*(\d{4})/(\d{1,2})/\d{1,2}", text)
    if not match:
        match = re.search(r"(?:linebank_)?(\d{4})[-_](\d{1,2})", html_path.stem, re.IGNORECASE)
    if not match:
        raise ValueError("無法從對帳單期間或檔名判斷帳單年月")
    return int(match.group(1)), int(match.group(2))

def validate(raw_t2, raw_t4, soup):
    warnings = []
    stated_bal = stated_amount(soup, "tab2", r"\$([0-9,]+)")
    if stated_bal is not None and len(raw_t2) > 1:
        last_bal = parse_amount(raw_t2[-1][3])
        if isinstance(last_bal, int) and last_bal != stated_bal:
            warnings.append(f"⚠ 台幣存款最終餘額不符：表格末列 ${last_bal:,}，頁面顯示 ${stated_bal:,}")

    stated_card = stated_amount(soup, "tab4", r"消費總金額\s+([0-9,]+)")
    if stated_card is not None and len(raw_t4) > 1:
        amount_index = header_index(raw_t4[0], "金額", "新臺幣金額")
        card_sum = sum(
            parse_amount(row[amount_index])
            for row in raw_t4[1:]
            if isinstance(parse_amount(row[amount_index]), int)
        )
        if card_sum != stated_card:
            warnings.append(f"⚠ 刷卡消費總金額不符：表格加總 ${card_sum:,}，頁面顯示 ${stated_card:,}")

    if warnings:
        for w in warnings:
            print(w)
        print("→ 請手動確認上述差異再使用 Excel 檔案")
    else:
        print("✓ 驗證通過：餘額與刷卡總金額均吻合")

# ── 讀取資料 ─────────────────────────────────────────────────────
with open(HTML, encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

raw_t2 = get_table(soup, "tab2")
raw_t4 = get_table(soup, "tab4")
statement_year, statement_month = statement_year_month(soup, HTML)

if not raw_t2:
    raise ValueError("缺少必要的台幣存款表格（tab2），拒絕產生不完整 Excel")

validate(raw_t2, raw_t4, soup)

data_t2 = raw_t2[1:]
if raw_t4:
    headers4, data_t4 = separate_card_dates(raw_t4[0], raw_t4[1:])
    headers4, data_t4 = separate_exchange_date(headers4, data_t4)
else:
    headers4, data_t4 = EMPTY_CARD_HEADERS, []
headers = ["入帳日" if header in {"日期", "交易日期"} else header for header in raw_t2[0]]
data_t2 = normalize_date_columns(headers, data_t2, statement_year, statement_month)
data_t4 = normalize_date_columns(headers4, data_t4, statement_year, statement_month)
OUT = OUTPUT_DIR / f"{statement_year:04d}-{statement_month:02d}_交易明細.xlsx"

# ── 統計計算 ─────────────────────────────────────────────────────
# 台幣存款：依交易說明分組
t2_by_type = defaultdict(lambda: {"count": 0, "total": 0})
for row in data_t2:
    typ = row[1]
    amt = parse_amount(row[2])
    if isinstance(amt, int):
        t2_by_type[typ]["count"] += 1
        t2_by_type[typ]["total"] += amt

# 刷卡：依交易說明（商戶）分組
t4_by_merchant = defaultdict(lambda: {"count": 0, "total": 0})
merchant_index = header_index(headers4, "商戶", "交易說明")
card_amount_index = header_index(headers4, "金額", "新臺幣金額")
for row in data_t4:
    merchant = row[merchant_index]
    amt = parse_amount(row[card_amount_index])
    if isinstance(amt, int):
        t4_by_merchant[merchant]["count"] += 1
        t4_by_merchant[merchant]["total"] += amt

final_balance = parse_amount(data_t2[-1][3]) if data_t2 else 0
card_net = sum(
    parse_amount(row[card_amount_index])
    for row in data_t4
    if isinstance(parse_amount(row[card_amount_index]), int)
)

# ── 建立 Excel ───────────────────────────────────────────────────
workbook = xlsxwriter.Workbook(str(OUT))

num_fmt  = workbook.add_format({"font_size": FONT_SIZE, "num_format": "#,##0;[Red]-#,##0", "border": 1})
cell_fmt = workbook.add_format({"font_size": FONT_SIZE, "border": 1, "text_wrap": True})
date_fmt = workbook.add_format({"font_size": FONT_SIZE, "border": 1, "num_format": "yyyy-mm-dd"})
table_header_fmt = workbook.add_format({
    "bold": True,
    "font_size": FONT_SIZE,
    "font_color": "#FFFFFF",
    "bg_color": "#4F81BD",
    "border": 1,
    "align": "center",
    "valign": "vcenter",
})

# 統計頁專用格式
title_fmt  = workbook.add_format({"bold": True, "font_size": FONT_SIZE, "bg_color": "#1F497D", "font_color": "#FFFFFF",
                                   "border": 1, "align": "center", "valign": "vcenter"})
grp_fmt    = workbook.add_format({"bold": True, "font_size": FONT_SIZE, "bg_color": "#2E75B6", "font_color": "#FFFFFF", "border": 1})
label_fmt  = workbook.add_format({"font_size": FONT_SIZE, "indent": 1, "border": 1})
num_stat   = workbook.add_format({"font_size": FONT_SIZE, "num_format": "#,##0;[Red]-#,##0", "border": 1})
total_fmt  = workbook.add_format({"bold": True, "font_size": FONT_SIZE, "bg_color": "#F4B942", "border": 1,
                                   "num_format": "#,##0;[Red]-#,##0"})
total_lbl  = workbook.add_format({"bold": True, "font_size": FONT_SIZE, "bg_color": "#F4B942", "border": 1})

# ── 統計頁 ───────────────────────────────────────────────────────
ws0 = workbook.add_worksheet("統計")
ws0.set_zoom(115)
ws0.set_column(0, 0, 24)
ws0.set_column(1, 1, 10)
ws0.set_column(2, 2, 16)

r = 0
ws0.merge_range(
    r, 0, r, 2,
    f"LINE Bank {statement_year}年{statement_month:02d}月 統計摘要",
    title_fmt,
)

# 台幣存款分組
r += 2
ws0.merge_range(r, 0, r, 2, "台幣存款", grp_fmt)
r += 1
ws0.write(r, 0, "交易類型",    grp_fmt)
ws0.write(r, 1, "筆數",        grp_fmt)
ws0.write(r, 2, "金額合計",    grp_fmt)

for typ, v in sorted(t2_by_type.items(), key=lambda x: x[1]["total"]):
    r += 1
    ws0.write(r, 0, typ,         label_fmt)
    ws0.write(r, 1, v["count"],  num_stat)
    ws0.write(r, 2, v["total"],  num_stat)

r += 1
ws0.write(r, 0, "期末餘額",  total_lbl)
ws0.write(r, 1, "",          total_lbl)
ws0.write(r, 2, final_balance, total_fmt)

# 刷卡分組
r += 2
ws0.merge_range(r, 0, r, 2, "刷卡消費（依商戶）", grp_fmt)
r += 1
ws0.write(r, 0, "商戶",      grp_fmt)
ws0.write(r, 1, "次數",      grp_fmt)
ws0.write(r, 2, "金額合計",  grp_fmt)

for merchant, v in sorted(t4_by_merchant.items(), key=lambda x: -x[1]["total"]):
    r += 1
    ws0.write(r, 0, merchant,    label_fmt)
    ws0.write(r, 1, v["count"],  num_stat)
    ws0.write(r, 2, v["total"],  num_stat)

r += 1
ws0.write(r, 0, "刷卡淨消費合計", total_lbl)
ws0.write(r, 1, "",               total_lbl)
ws0.write(r, 2, card_net,         total_fmt)

# ── 台幣存款記錄 ─────────────────────────────────────────────────
ws1 = workbook.add_worksheet("台幣存款記錄")
ws1.freeze_panes(1, 0)
ws1.set_zoom(115)

col_widths = [col_width([headers] + data_t2, i) for i in range(len(headers))]
ws1.add_table(0, 0, len(data_t2), len(headers) - 1, {
    "style": "Table Style Medium 2",
    "total_row": False,
    "columns": [{"header": h, "header_format": table_header_fmt} for h in headers],
})
for ci, w in enumerate(col_widths):
    ws1.set_column(ci, ci, w)
for ri, row in enumerate(data_t2, start=1):
    for ci, val in enumerate(row):
        fmt = num_fmt if ci in (2, 3) else date_fmt if headers[ci] == "入帳日" else cell_fmt
        if ci in (2, 3):
            ws1.write_number(ri, ci, parse_amount(val), fmt)
        elif headers[ci] == "入帳日":
            ws1.write_datetime(ri, ci, val, fmt)
        else:
            ws1.write(ri, ci, val, fmt)

# ── 刷卡記錄 ─────────────────────────────────────────────────────
ws2 = workbook.add_worksheet("刷卡記錄")
ws2.freeze_panes(1, 0)
ws2.set_zoom(115)

col_widths4 = [col_width([headers4] + data_t4, i) for i in range(len(headers4))]
ws2.add_table(0, 0, max(len(data_t4), 1), len(headers4) - 1, {
    "style": "Table Style Medium 2",
    "total_row": False,
    "columns": [{"header": h, "header_format": table_header_fmt} for h in headers4],
})
for ci, w in enumerate(col_widths4):
    ws2.set_column(ci, ci, w)
for ri, row in enumerate(data_t4, start=1):
    for ci, val in enumerate(row):
        if ci == card_amount_index:
            ws2.write_number(ri, ci, parse_amount(val), num_fmt)
        elif headers4[ci] in {"消費日", "入帳日", "換匯日"}:
            if val is None:
                ws2.write_blank(ri, ci, None, date_fmt)
            else:
                ws2.write_datetime(ri, ci, val, date_fmt)
        else:
            ws2.write(ri, ci, val, cell_fmt)

workbook.close()
print(f"✓ {OUT}  ({OUT.stat().st_size:,} bytes)")
