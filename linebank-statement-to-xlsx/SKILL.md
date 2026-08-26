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
unset BANK_STATEMENT_PASSWORD
```

---

## Step 3：下載 iframe HTML

對帳單在 `<iframe>` 內，JSON 資料需認證 cookie，**不可直接開 iframe URL**。

```bash
cat <<'EOF' | DISPLAY=:1 agent-browser eval --stdin > linebank_YYYY_MM.html
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

**eval 輸出為 JSON 字串**，須以 JSON parser 解碼後再覆寫成 HTML；不可把帶引號
與 escape sequences 的原始 eval 輸出直接交給產生器。

---

## Step 4：產生 Excel

```bash
uv run --with xlsxwriter --with beautifulsoup4 \
  scripts/gen_linebank_xlsx.py linebank_YYYY_MM.html
```

輸出 `linebank_YYYY_MM.xlsx` 與 HTML 同目錄。

**內建驗證（自動）：**
- tab2 末列餘額 == 頁面「台幣存款總餘額」
- tab4 淨加總 == 頁面「刷卡消費總金額」（含退貨負數）

---

## Troubleshooting

| 情況 | 處理 |
|------|------|
| Chrome 無法啟動 | `ls /tmp/.X11-unix/` 確認；或 `agent-browser.json` 改 `"headed": false` |
| iframe 資料空白 | 缺 cookie，必須從登入後的主頁取 `contentDocument`，不可直接開 iframe URL |
| 驗證碼看不清 | `agent-browser screenshot` 目視，或點當次 snapshot 的刷新控制項 |
| 刷卡金額驗證不符 | 確認加總含退貨負數；頁面顯示為淨值 |
| `parse_amount` 回字串 | 空白格或 `-` 佔位符無法轉 int，金額欄寫入時會變文字 |
