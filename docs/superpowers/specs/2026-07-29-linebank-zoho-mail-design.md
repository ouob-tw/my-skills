# LINE Bank Zoho Mail 自動取信設計

## 目標

擴充 `linebank-statement-to-xlsx` skill，使其能透過 Zoho Mail MCP 自動從
`/bank/linebank` 資料夾取得指定月份的 LINE Bank 電子對帳單信件，解析帳單
連結，再接續既有的瀏覽器登入、HTML 擷取與 Excel 產生流程。

## 月份判定

- 以信件主旨中的 `YYYY年M月電子對帳單` 作為帳單月份。
- 使用者未指定月份時，選擇主旨帳單月份最新的一封。
- 不使用收信時間推定帳單月份，因對帳單可能在次月寄送或之後轉寄。
- 本次真實 E2E 的目標月份固定為 2026 年 6 月。

## Zoho Mail 取信流程

1. 使用 Zoho Mail MCP 取得目前帳號與 `accountId`。
2. 列出全部資料夾，依完整路徑精確定位 `/bank/linebank`。
3. 搜尋或列出候選郵件。
4. 只保留回傳 `folderId` 等於目標資料夾 ID 的郵件。Zoho 搜尋可能混入其他
   資料夾結果，不能只相信搜尋條件。
5. 從主旨解析帳單月份，依指定月份選取信件；同月份有多封時選收信時間最新者。
6. 讀取選定信件的完整 HTML 內容。

## 連結解析

1. 擷取 HTML 中所有 `href`。
2. 對 LINE Bank `interact-collector/t/mbc` 追蹤網址解析 query string。
3. URL decode `l` 參數，取得真正目的網址。
4. 選擇 host 為 `myestatement.linebank.com.tw` 且 path 包含
   `/interact-inspector/billViewer/init` 的連結。
5. 保留 `uuid` 及既有 query string；不得以圖片 URL、促銷網址或前一期帳單
   連結取代當月帳單連結。

## 既有流程整合

解析出的當月 `billViewer` 連結直接交給既有 agent-browser 流程：

1. 開啟連結。
2. 輸入身分證字號與圖形驗證碼。
3. 從已驗證頁面的 iframe 取得 HTML。
4. 執行 `scripts/gen_linebank_xlsx.py` 產生 Excel 並完成金額驗證。

Zoho MCP 不可用時，保留現有 `.eml` 輸入流程作為明確備援；不得默默改用其他
信箱或其他資料夾。

## 錯誤處理

遇到下列情況時停止並回報具體缺口：

- 找不到 Zoho Mail 帳號或 `/bank/linebank`。
- 目標資料夾內沒有指定帳單月份的信件。
- 信件 HTML 沒有可解碼的當月 `billViewer` 連結。
- 需要登入資料或人工辨識驗證碼。
- iframe 尚未載入或帳單驗證不一致。

不得將其他月份、其他資料夾或搜尋結果中的第一封信當成成功結果。

## 驗證

### RED

以既有 skill 回答「從 Zoho Mail 的 linebank 資料夾抓 2026 年 6 月對帳單並取得
帳單連結」；確認既有內容只支援 `.eml`，缺少帳號、資料夾、月份選擇與追蹤網址
解碼流程。

### GREEN

- 驗證 skill frontmatter 與目錄格式。
- 驗證 skill 明確包含帳號探索、完整資料夾路徑、`folderId` 二次過濾、主旨月份
  判定、HTML 讀取、`l` 參數解碼與 `.eml` 備援。
- 執行既有 Excel 腳本測試或可用的代表性輸入，確保原流程未被破壞。

### 真實 E2E

由 Terra subagent 使用更新後的 skill 與真實 Zoho Mail MCP：

1. 定位 `/bank/linebank`。
2. 找到主旨帳單月份為 2026 年 6 月的信件。
3. 讀取真實信件 HTML。
4. 回報選中信件的主旨、message ID、folder ID，以及解碼後的當月
   `billViewer` 連結。
5. 接續 agent-browser 開啟連結；若登入或驗證碼需要人工作業，回報精確阻塞點，
   不得宣稱 E2E 通過。

