---
name: linebank-statement-to-xlsx
description: Use when working with LINE Bank electronic statements, Zoho Mail /bank/linebank messages, .eml statement exports, billViewer links, transaction extraction, or monthly Excel generation.
---

# LINE Bank 對帳單 → Excel

## Overview

```
Zoho Mail（預設）或 .eml（備援）→ 當月 billViewer URL
→ agent-browser 登入(身分證+驗證碼) → iframe HTML → 驗證 → xlsx
```

## Requirements

- 自動取信：已連線且具唯讀權限的 Zoho Mail MCP。
- 解析與輸出：`uv`、`beautifulsoup4`、`xlsxwriter`。
- 帳單登入：`agent-browser`。有頭模式需要 display（通常為 `DISPLAY=:1`）；
  無螢幕環境在 `agent-browser.json` 設定 `headed=false`。
- 憑證：專案根目錄 `.env` 的 `BANK_STATEMENT_PASSWORD`。

---

## Step 0：登入憑證預檢

當任務需要開啟帳單內容或產生 Excel 時，在流程一開始只讀取專案根目錄
`.env` 的 `BANK_STATEMENT_PASSWORD`。不要顯示 `.env` 全文或將值寫入輸出、
指令紀錄、截圖、Git、報告。將值載入暫時的程序環境，供登入步驟使用。

若變數不存在或空白，立即詢問使用者提供 LINE Bank 對帳單的身分證字號／檔案
密碼，再繼續其他步驟；不得猜測。若任務只要求擷取信件或連結，不需要讀取或詢問
此憑證。

---

## Step 1：取得指定月份的對帳單 URL

### 1A：從 Zoho Mail 自動取信（預設）

所有郵件操作都維持唯讀；不得移動、刪除、標記或回覆信件。

1. 呼叫 `ZohoMail_getMailAccounts` 取得帳號。只有一個帳號時使用該帳號；多個
   帳號時優先選 `isDefaultAccount=true` 且 `enabled=true`，仍不唯一就先詢問。
2. 以該 `accountId` 呼叫 `ZohoMail_getAllFolders`，要求
   `folderId,folderName,path`，並以完整路徑精確匹配 `/bank/linebank`。
3. 呼叫 `ZohoMail_SearchEmails`，使用 `searchKey=in:<folderId>`、`limit=200`。
   若有分頁就繼續，直到找到目標月份或沒有更多結果。
4. **再次過濾每筆結果的 `folderId == <folderId>`。** Zoho 搜尋可能混入其他
   資料夾郵件；不可相信搜尋條件後直接取第一封。
5. 從主旨解析 `(\d{4})年\s*(\d{1,2})月電子對帳單`：
   - 使用者指定月份時，只保留該帳單年月。
   - 未指定月份時，選主旨帳單年月最新者。
   - 同月份多封時，選 `receivedTime` 最新者。
   - 不以收信月份推定帳單月份，因信件可能次月寄出或稍後轉寄。
6. 使用選定郵件的真實 `folderId`、`messageId` 呼叫
   `ZohoMail_getMessageContent`，並設 `includeBlockContent=true`。
7. 從回傳 HTML 的 `href` 解析連結：
   - 若為 `estatement-material.linebank.com.tw/interact-collector/t/mbc`，
     以 `urllib.parse.parse_qs` 取得並 URL decode query parameter `l`。
   - 只接受 host 為 `myestatement.linebank.com.tw` 且 path 包含
     `/interact-inspector/billViewer/init` 的目的網址。
   - 當月連結不含目的網址參數 `l=l`；含 `l=l` 的是「前一期」入口。
   - 不得把促銷網址、圖片 `src` 或開信追蹤像素當成帳單連結。

可用此核心邏輯解碼；`parse_qs` 已處理 percent decoding，不要重複 decode：

```python
from html import unescape
from urllib.parse import parse_qs, urlparse

def decode_billviewer(href):
    href = unescape(href)
    parsed = urlparse(href)
    if (
        parsed.hostname == "estatement-material.linebank.com.tw"
        and parsed.path == "/interact-collector/t/mbc"
    ):
        href = parse_qs(parsed.query).get("l", [""])[0]
        parsed = urlparse(href)
    if (
        parsed.hostname == "myestatement.linebank.com.tw"
        and "/interact-inspector/billViewer/init" in parsed.path
        and parse_qs(parsed.query).get("l") != ["l"]
    ):
        return href
    return None
```

若找不到帳號、完整資料夾路徑、目標月份信件或唯一當月連結，停止並回報缺少
哪一項；不得換用其他資料夾或其他月份冒充成功。帳單 URL 含個人識別參數，
不得提交到 Git 或公開紀錄。

### 1B：從 `.eml` 取出 URL（Zoho MCP 不可用時）

解析 `.eml` 的 `text/html` MIME part，將其中的 `href` 交給 1A 的
`decode_billviewer`。同一 UUID 加 `&l=l` 是前月連結。

---

## Step 2：agent-browser 登入

```bash
# 確認 display（無螢幕環境改 agent-browser.json "headed": false）
ls /tmp/.X11-unix/   # X1 → DISPLAY=:1

DISPLAY=:1 agent-browser open "https://myestatement.linebank.com.tw/.../init?uuid=<UUID>"
DISPLAY=:1 agent-browser wait --load networkidle
DISPLAY=:1 agent-browser screenshot /tmp/check.png   # 目視確認驗證碼文字
```

執行 `agent-browser snapshot -i`，依 label、role 和可見文字取得當次的身分證、
驗證碼、確認及刷新控制項 refs。Refs 會隨頁面重新載入而改變，不得沿用範例值或
前次執行的 refs。

```bash
DISPLAY=:1 agent-browser fill <password-ref> "$BANK_STATEMENT_PASSWORD"
DISPLAY=:1 agent-browser fill <captcha-ref> "<captcha>"
DISPLAY=:1 agent-browser click <confirm-ref>
DISPLAY=:1 agent-browser wait --load networkidle
DISPLAY=:1 agent-browser wait --fn \
  "document.querySelector('iframe')?.contentDocument?.querySelector('#tab2 .table-scroll table') !== null"
unset BANK_STATEMENT_PASSWORD
```

登入頁本身也可能包含空 iframe，所以不得以「iframe 存在」判定登入成功。只有當
iframe 內出現 `#tab2 .table-scroll table` 才能進入下載步驟；等待失敗時重新截圖並
辨識新的驗證碼，不得保存空 iframe 或把驗證碼失敗當成成功。

---

## Step 3：下載 iframe HTML

對帳單在 `<iframe>` 內，JSON 資料需認證 cookie，**不可直接開 iframe URL**。

```bash
cat <<'EOF' | DISPLAY=:1 agent-browser eval --stdin \
  | uv run python -c 'import json,sys; sys.stdout.write(json.load(sys.stdin))' \
  > private/banks/linebank/raw/YYYY/YYYY-MM.html
(function(){
  const doc = document.querySelector('iframe').contentDocument;
  let css = '';
  for (const s of doc.styleSheets) {
    try { for (const r of s.cssRules) css += r.cssText + '\n'; } catch(e) {}
  }
  return doc.documentElement.outerHTML
    .replace(/<link[^>]+main\.css[^>]*>/g, `<style>${css}</style>`);
})()
EOF
```

**eval 輸出為 JSON 字串**；上述管線會先以 JSON parser 解碼，再把純 HTML 寫入
raw。不可省略解碼步驟，或把帶引號與 escape sequences 的原始 eval 輸出直接交給
產生器。

---

## Step 4：產生 Excel

產生或整改 Excel 時同時使用 `excel-table-style` Skill，依其共用契約計算每張工作表
的欄寬與 Zoom；本 Skill 只保留 LINE Bank 來源及欄位特有規則。
所有輸出工作表（包含統計頁）的基礎字體固定為 `18pt`、Zoom 固定為 `115%`；
粗體、字色與底色維持欄位契約，欄寬按 `18 / 11` 縮放後仍限制在 10–40。

```bash
uv run --with xlsxwriter --with beautifulsoup4 \
  skills/linebank-statement-to-xlsx/scripts/gen_linebank_xlsx.py \
  private/banks/linebank/raw/YYYY/YYYY-MM.html \
  private/banks/linebank/output/YYYY
```

原始 HTML 內容不改寫，按 `YYYY-MM.html` 留在 `private/banks/linebank/raw/YYYY/`；
Excel 以 `YYYY-MM_交易明細.xlsx` 輸出到 `private/banks/linebank/output/YYYY/`。資料已
由資料夾表示銀行，不在檔名加銀行前綴；兩者都不得提交 Git。

輸出欄位契約：

- `台幣存款記錄` 的銀行交易日期命名為 `入帳日`。
- `刷卡記錄` 固定分成 `消費日` 與 `入帳日` 兩欄。
- billViewer 只提供單一刷卡日期時，保存為 `消費日` 並讓 `入帳日` 留空；不複製或
  推定第二個日期。
- 舊 HTML 將兩日放在同一格時，依來源中的分隔符拆開後再輸出。
- 若來源提供 `外幣消費金額/換匯日`，輸出時拆成 `外幣消費金額` 與 `換匯日`。
- 所有已知日期以 Excel 日期值保存並顯示為 `yyyy-mm-dd`；空白日期維持空白。

**內建驗證（自動）：**
- tab2 末列餘額 == 頁面「台幣存款總餘額」
- tab4 淨加總 == 頁面「刷卡消費總金額」（含退貨負數）

若需重建仍保存為 `MM_files/saved_resource.html` 的 2025 舊格式年度彙整，才執行
`uv run skills/linebank-statement-to-xlsx/scripts/convert_legacy_2025.py`；legacy 輸出也遵守
相同日期欄位契約。一般月份不得使用此 legacy 入口。

---

## Troubleshooting

| 情況 | 處理 |
|------|------|
| Chrome 無法啟動 | `ls /tmp/.X11-unix/` 確認；或 `agent-browser.json` 改 `"headed": false` |
| iframe 資料空白 | 缺 cookie，必須從登入後的主頁取 `contentDocument`，不可直接開 iframe URL |
| 驗證碼看不清 | `agent-browser screenshot` 目視，或點當次 snapshot 的刷新控制項 |
| 刷卡金額驗證不符 | 確認加總含退貨負數；頁面顯示為淨值 |
| `parse_amount` 回字串 | 空白格或 `-` 佔位符無法轉 int，金額欄寫入時會變文字 |
