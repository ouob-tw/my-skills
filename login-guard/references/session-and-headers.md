# 登入後：session、Cookie、安全標頭與登入紀錄

## Session（登入的裝置）

規則與理由：

- **token 是 32 位元組亂數，伺服器只存 SHA-256**：資料庫外流也拿不到能用的 Cookie。每筆另有一個短的公開 ID，給設定頁的裝置清單與紀錄用。
- **兩個期限**：從登入起算的絕對期限（例如 30 天），加上閒置期限（例如 7 天沒有任何已登入的請求）。每個請求都檢查；過期與作廢的效果一樣：API 回 401、頁面轉登入頁、事件串流下一次心跳就斷。
- **最後使用時間不要每個請求都寫**：每台每分鐘最多寫一次，確切時間留在記憶體；正常關機時把沒寫的補寫。
- **記下這個 session 過了哪一種第二步**（`totp`、`passkey`）。上線兩步登入時，沒有這個欄位的舊 session 一律當過期，不必改寫資料就能讓所有舊裝置重新登入。
- **作廢**：刪掉那筆資料，下一個請求就 401。設定頁列出所有已登入的裝置（名稱從 User-Agent 推、登入時間、最後使用時間），可以逐台作廢。
- **全部作廢的時機**：改密碼、更換或清除 TOTP 金鑰。原因是這些動作通常代表舊的秘密可能外流，舊 session 可能就是別人的。發起的這台可以保留。
- **登出**：伺服器刪掉這筆 session，再用與設定時相同的屬性清掉 Cookie，頁面用 `location.replace('/login')`，按上一頁不會回到後台。

## Cookie

| 屬性 | 值 | 理由 |
|---|---|---|
| 名稱 | 每個服務自己的名稱 | Cookie 屬於主機名稱、不分 port，同一個主機名稱上的兩個服務用同名會互相蓋掉登入 |
| `HttpOnly` | 開 | |
| `SameSite` | `Strict` | 副作用見表下 |
| `Secure` | 經信任代理的 HTTPS 時開 | 只走加密連線；本機 http 測試照常能登入。一定是 HTTPS 的服務可以改用 `__Host-` 前綴，瀏覽器會強制 `Secure`、`Path=/`、不帶 `Domain` |
| `Path` | `/`（第二步的 Cookie 用 `/api/login`） | 第二步的 token 只有登入端點收得到 |
| `Max-Age` | 剩下的登入期限 | 與伺服器的期限一致 |
| `Domain` | 不設 | 只給這個主機名稱，子網域拿不到 |

- **清除時帶相同屬性**：設定時有 `Secure`、清除時沒有，瀏覽器會忽略這個清除。
- **`SameSite=Strict` 的副作用**：從別的網站或主畫面捷徑（安裝的 PWA）打開時，第一個請求不帶 Cookie，看起來像沒登入。處理法：頂層導覽（`Sec-Fetch-Mode: navigate`）而且 `Sec-Fetch-Site` 不是 `same-origin`、又沒帶 Cookie 時，回一個 200、`Cache-Control: no-store`、不含資料的小頁，由它 `location.replace(location.href.split('#')[0])` 重新載入自己；重新載入是同站請求，有 Cookie 就進後台，仍沒有才轉登入頁，最多多一跳。
- **跨站請求偽造**：SvelteKit 內建的來源檢查會擋跨站送來的表單，保持開著。FastAPI 沒有，要自己擋：會改狀態的請求檢查 `Origin`，並要求 JSON。

```python
from fastapi import Request

SAFE = {"GET", "HEAD", "OPTIONS"}


def cross_site_write(request: Request, origin: str) -> bool:
    """別的網站可能發起的寫入請求就回 True（在中介層回 403）。瀏覽器的 POST 一定帶 Origin；
    沒帶時看 Sec-Fetch-Site。一般 HTML 表單送不出 JSON，所以也要求 JSON。"""
    if request.method in SAFE:
        return False
    sent = request.headers.get("origin")
    if sent is not None and sent != origin:
        return True
    if sent is None and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return True
    return not request.headers.get("content-type", "").startswith("application/json")
```

FastAPI：`response.set_cookie(SESSION_COOKIE, token, max_age=max_age, path="/", httponly=True, samesite="strict", secure=request.state.https)`，清除用 `response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=request.state.https)`。SvelteKit：`cookies.set(SESSION_COOKIE, token, { path: '/', httpOnly: true, sameSite: 'strict', secure: locals.https, maxAge })`，清除用 `cookies.delete(SESSION_COOKIE, { path: '/', httpOnly: true, sameSite: 'strict', secure: locals.https })`。

## 安全標頭

**每個回應都要有**：頁面、API、靜態檔、403、轉址、框架自己的錯誤頁。放在最外層（[client-ip.md](client-ip.md) 的自訂伺服器或中介層），SvelteKit 另在 `handle` 補一次。

| 標頭 | 值 | 理由 |
|---|---|---|
| `Content-Security-Policy` | `frame-ancestors 'none'; object-src 'none'; base-uri 'self'` | 不能被別的網站嵌入（點擊劫持）、不跑外掛、`<base>` 不能指到別處；這幾項不會弄壞一般頁面，`script-src` 等確認頁面不受影響再加 |
| `X-Frame-Options` | `DENY` | |
| `X-Content-Type-Options` | `nosniff` | |
| `Referrer-Policy` | `same-origin` | 點外部連結時不把後台網址告訴別的網站 |
| `Strict-Transport-Security` | `max-age=31536000`，只在 HTTPS 回應 | 一年內瀏覽器只用 HTTPS 連這個主機名稱；http 回應帶了也沒用，本機 http 測試才不受影響 |

[client-ip.md](client-ip.md) 的程式匯入的 `securityHeaders(https)`（Node）／`security_headers(https)`（Python）就是回傳上表的（名稱, 值）清單，HTTPS 時才含 HSTS；名稱大小寫不拘，那邊比對 CSP 時先轉小寫。

回應原本就帶的 CSP（例如使用者上傳的檔案用 `sandbox`）要保留：另外加一條 CSP 標頭（`append`），瀏覽器會同時執行兩條政策；用 set 蓋掉它，上傳的 HTML 就能跑 script。

## 登入前的頁面不透露東西

登入頁所有人（整個台灣）都看得到：

- 登入頁的 HTML、它載入的資料、登入 API 的錯誤，都不帶主機的絕對路徑、家目錄、內部主機名稱或網址、帳號名稱。要提示主機指令時寫相對的說法（「在專案資料夾執行 `…`」）。
- 錯誤只回固定的錯誤碼（`wrong_password`、`wrong_code`、`second_step_expired`、`locked`），不回例外訊息。

## 登入紀錄

每個登入相關事件寫一行結構化紀錄（JSON 一行一筆）：

| 欄位 | 內容 |
|---|---|
| `message` | 事件：`login_password`、`login_totp`、`login_passkey`、`login_passwordless`、`passkey_enroll`、`passkey_delete`、`logout`、`login_locked` |
| `result` | `start`（只是開始，例如拿到 passkey 挑戰值）、`success`、`failure` |
| `reason` | 失敗時必填：回給頁面的錯誤碼；被鎖是 `locked`；程式例外是 `exception`；瀏覽器回報的錯誤名稱（`NotAllowedError`、`InvalidStateError`，清單外記 `other`） |
| `client_ip` | 入口算好的真實 IP |
| `device_id` | 有登入的 session 或剛建立的 session 時，用公開的短 ID |
| `user_agent` | 截短（例如 300 字） |
| 其他 | `passkey_id`、`via`（`settings`、`host_code`）；`login_locked` 另帶 `during`（哪個事件鎖住的）與 `lock_seconds` |

- **絕不寫**：密碼、TOTP 數字、登記碼、Cookie、任何 token、WebAuthn 回應內容、公鑰。請求內容的紀錄（例如錯誤回報）也要遮掉 `password`、`code` 欄位。
- **每個請求剛好一行**：把它包在路由外面（一個包裝函式或裝飾器），依回應狀態決定 `success`／`failure`，`reason` 從回應的錯誤碼取；例外也寫一行再往外丟。這樣不會有哪個提早 return 的分支漏寫。
- `login_locked` 用 WARNING，其他用 INFO。
- 瀏覽器回報 WebAuthn 錯誤的端點：只收流程名稱與錯誤名稱，內容超過 1 KB 就拒絕，全站每分鐘最多記 100 筆，換 IP 也灌不爆紀錄。
