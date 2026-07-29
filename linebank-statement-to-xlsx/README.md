# LINE Bank 電子對帳單轉 Excel

## 用途說明

這個 Skill 用於自動取得 LINE Bank 電子對帳單，登入帳單頁面並產生 Excel。

預設從 Zoho Mail 的 `/bank/linebank` 資料夾讀取指定月份的信件，也支援以
`.eml` 檔案作為備援來源。產生的 Excel 包含：

- 統計摘要
- 台幣存款記錄
- 刷卡記錄

流程會核對期末存款餘額及刷卡淨額，避免輸出與原始帳單不一致。

## 簡易流程表

| 步驟 | 處理內容 | 產出 |
|---|---|---|
| 1 | 從 Zoho Mail `/bank/linebank` 選取指定帳單月份的信件 | 信件 HTML |
| 2 | 解碼信件中的 LINE Bank 當期帳單連結 | `billViewer` URL |
| 3 | 使用帳單密碼及圖形驗證碼登入 | 已驗證的帳單頁面 |
| 4 | 從登入後頁面的 iframe 擷取帳單 HTML | `linebank_YYYY_MM.html` |
| 5 | 解析存款與刷卡資料並執行金額驗證 | `linebank_YYYY_MM.xlsx` |

若只需要擷取信件或帳單連結，不需要提供帳單密碼。

## 工具要求

| 工具／設定 | 用途 |
|---|---|
| Zoho Mail MCP | 唯讀取得帳號、資料夾及信件內容 |
| `agent-browser` | 開啟 LINE Bank、處理驗證碼並取得登入後的 iframe |
| `uv` | 執行 Python 產生器及管理執行期依賴 |
| `beautifulsoup4` | 解析帳單 HTML |
| `xlsxwriter` | 產生 Excel |
| 專案根目錄 `.env` | 保存 `LINEBANK_STATEMENT_PASSWORD`；不得提交至 Git |
| Display 或 headless browser | 有頭模式通常使用 `DISPLAY=:1`；無螢幕環境使用 headless |

詳細的 Agent 執行規則請參閱 [SKILL.md](SKILL.md)。
