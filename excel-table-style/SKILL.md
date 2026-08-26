---
name: excel-table-style
description: Use when 產生XLSX表格
---


## 一、套件選用

| 階段 | 套件 | 理由 |
|---|---|---|
| 反覆調整、要自動驗證數字 | **openpyxl** | 不寫公式快取，可被 LibreOffice headless 重算驗證 |
| 定版、要格式化表格 | **xlsxwriter** | 表格(ListObject)最穩、樣式內建；缺點是公式值為快取，非 Excel 工具不重算 |

## 二、欄寬

- **程式計算、不寫死**。中文字寬 2、半形 1，取「右邊有數值的列」中最長標籤 + 2 邊距：

```python
def dispw(s): return sum(2 if ord(ch)>0x2E7F else 1 for ch in s)
a_width = max(dispw(s) for s in a_labels) + 2
```

## 三、預設縮放

- 三頁都 `set_zoom(240)`，開檔即 **240%**
- 範圍 10–400；每頁可各自設；只影響螢幕檢視，不影響列印（列印是 `set_print_scale()`）

```python
for _ws in (s,c,p): _ws.set_zoom(240)
```