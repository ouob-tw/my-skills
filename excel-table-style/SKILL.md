---
name: excel-table-style
description: Use whenever creating, regenerating, or restyling XLSX tables with openpyxl or XlsxWriter, especially for column widths, CJK text, dates, wrapping, filters, freeze panes, zoom, and post-write workbook validation.
compatibility: Requires Python 3.10+; workbook operations may use openpyxl or XlsxWriter.
---

# Excel 表格樣式

建立或整改 XLSX 時，讓資料型別、欄寬與檢視設定一致且可驗證。既有專案契約優先；
本 Skill 提供沒有更具體規範時的預設值。

## 執行流程

1. 先盤點工作表、表頭、資料型別、公式、既有 Table/AutoFilter、凍結窗格與下游讀取契約。
2. 保留既有函式庫；編輯既有活頁簿通常用 `openpyxl`，從零建立且需要 Excel Table 時通常用 `XlsxWriter`。不要只為樣式切換函式庫。
3. 先寫入最終值與 `number_format`，再逐張工作表計算欄寬。插入、刪除或拆分欄位後重新計算全部已使用欄位，不沿用舊欄寬。
4. 套用表頭、數字格式、篩選、凍結窗格、換行與縮放。只有契約要求 Excel Table（ListObject）時才建立；既有契約若只允許 AutoFilter 就維持原狀。
5. 儲存後重新開啟活頁簿，逐張驗證表頭、資料型別、公式、日期格式、欄寬、工作表數量與既有結構。

完成條件：表頭水平置中、垂直靠上；內容依語意型別對齊，文字靠左、數字靠右，
且一律垂直靠上。所有已使用欄位符合下列欄寬契約，長文字可讀，日期與數字仍是 Excel 原生值，
且重新開啟後結構與資料筆數不變。

## 字體契約

- 字體大小是輸出契約，必須由專案或任務明確指定；不要從既有活頁簿中混雜的字體
  反推，也不要用 Zoom 取代字體大小。
- 契約指定 `18pt` 時，所有已使用儲存格的基礎字體固定為 `18pt`；保留既有粗體、
  斜體、字色與字型名稱，再按 `18 / 11` 縮放欄寬並將 Zoom 設為 `115%`。
- 任務指定 `Noto Sans` 且活頁簿包含繁體中文時，實際 XLSX 字型名稱使用
  `Noto Sans CJK TC`；儲存格與圖表都要明確指定，不依賴作業系統字型 fallback。
- 任務指定微軟正黑體時，實際 XLSX 字型名稱使用 `Microsoft JhengHei`；儲存格、圖表
  與頁首頁尾都要明確指定。非 Windows 環境缺少該字型時，渲染工具會使用替代字型，
  因此本機截圖只能驗證版面，實際字型外觀以安裝該字型的 Microsoft Excel 為準。
- 不依任意字體大小連續推算 Zoom；只使用「檢視設定」中的明確 mapping。

## 欄寬契約

- 依儲存格的「顯示內容」計算，不使用 Python 物件的 `str()` 表示。日期顯示為 `yyyy-mm-dd` 時按 10 個半形字元計算，不按 `2026-01-01 00:00:00` 計算。
- 契約為 18pt 時，`yyyy-mm-dd` 日期欄使用 `fitted_width(..., font_size=18)` 計算後的名目欄寬至少為 18；固定設成 15 會在 Microsoft Excel 顯示 `####`，即使 LibreOffice 或 openpyxl 沒有報錯。
- 每個半形字元算 1 單位；Unicode East Asian Width 為 `W` 或 `F` 的 CJK／全形字元算 2 單位；多行文字取最長一行。
- 表頭加 2 單位，資料加 1 單位，取該欄最大值。
- 預設最小欄寬 10、最大欄寬 40。專案可為識別碼、備註等欄位設定具理由的局部 override。
- 計算值超過最大欄寬時，欄寬設為最大值並開啟 `wrap_text`；不要讓單一長文字把整張表拉寬。
- 逐張工作表獨立計算；資料列多寡本身不影響欄寬，內容的最長顯示值才影響。
- 若字體顯著大於 Excel 預設 11pt，可按 `font_size / 11` 縮放內容寬度，但仍受最大欄寬限制。

使用 [`scripts/column_width.py`](scripts/column_width.py) 的 `display_width()` 與
`fitted_width()` 作為確定性的共用算法；它不讀寫工作簿，可由 `openpyxl` 與
`XlsxWriter` 呼叫。

## 表格契約

- 第一列使用明確且唯一的表頭；表頭水平置中、垂直靠上並啟用換行，不使用會裁切換行文字的固定列高，並凍結表頭列。
- 一般文字水平靠左，數字、金額、百分比、日期、時間與數字公式結果水平靠右；所有內容儲存格一律垂直靠上。
- 交易 ID、發票號碼、帳號等識別字串即使全由數字組成，仍視為文字靠左；空白儲存格依所屬欄位語意對齊。
- 日期、時間與數字保存為 Excel 原生型別，缺值維持空白。顯示格式不應把文字偽裝成日期或數字。
- 金額欄使用一致的千分位／負數格式；文字欄依內容決定是否換行，換行不改變原定對齊方式。
- 篩選範圍精確涵蓋表頭與資料。是否建立 Excel Table 由既有專案契約決定，不以樣式需求擅自改變結構。
- 保留既有工作表順序、名稱、公式、合併儲存格、命名範圍及下游依賴，除非任務明確要求修改。
- 內部導覽連結預設維持單行並關閉自動換行；長內容欄位的換行規則不得套用到導覽按鈕。

## 圖表與實際畫面

- 專案有明確圖表字級時，設定 title、axis、legend 與 data label 的字型，不使用 writer 預設小字。主要文字依專案基礎字級；次要文字只有在專案允許時才縮小。
- 涉及圖表位置、列印版面或使用者要求視覺確認時，把實際 XLSX 轉成 PDF／PNG 並逐頁查看；writer 屬性、openpyxl 重開與 PDF 成功產生都不能代替畫面檢查。

## 檢視設定

- 縮放只影響螢幕檢視，不影響欄寬或列印比例。
- 字體為 `10pt` 時將 Zoom 設為 `240%`；字體為 `18pt` 時設為 `115%`。
- 其他字體不做線性推算：整改既有活頁簿時保留原縮放，新活頁簿預設 `100%`，除非使用者或專案契約另有指定。
- 對所有資料工作表套用規則，不假設固定工作表數量。

使用 `recommended_zoom()` 取得上述明確 mapping；回傳 `None` 表示應套用既有檔或
新檔的 fallback 規則。

## 驗證

先執行共用算法的自我測試：

```bash
uv run excel-table-style/scripts/column_width.py --self-test
```

再重新開啟實際輸出並檢查：

- 每個已使用欄位的寬度都在允許範圍內。
- 日期儲存格是日期值且顯示格式正確。
- 18pt 的 `yyyy-mm-dd` 日期欄名目寬度至少 18，且實際畫面不出現 `####`。
- 超長文字欄已達最大寬度並啟用換行。
- 表頭水平置中、垂直靠上，換行後未被列高裁切；文字內容靠左上、數字內容靠右上。
- 拆欄或插欄後，欄寬對應目前欄位而非舊欄位位置。
- 表頭、資料列數、公式與既有 Table/AutoFilter 契約未改變。
- 內部導覽文字沒有自動換行；若有圖表或列印版面，已逐頁檢查實際 PDF／PNG。
