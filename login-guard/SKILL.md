---
name: login-guard
description: Use when adding or reviewing login protection for a web app (FastAPI, SvelteKit / Node or similar) — limiting access to Taiwan IPs at the reverse proxy or in-app with GeoIP, reading the real client IP behind a proxy, password plus TOTP two-step login, passkeys (WebAuthn) as a second step or passwordless login, lockout after failed attempts, session lifetime and revocation, login event logs, or cookie and security headers.
---

# 登入防護

給管理後台這類「只有少數人該進來」的網站用：由外往內一層一層擋，每一層都假設外面那層可能失守。

## 防線順序

| 順序 | 防線 | 為什麼放這裡 | 參考檔 |
|---|---|---|---|
| 1 | 反向代理只放台灣與內網（GeoIP） | 國外的流量連登入頁都看不到；程式出錯也不會漏 | [proxy-geoip.md](references/proxy-geoip.md) |
| 2 | 程式只接受代理與本機的連線，真實 IP 只信代理轉來的 | 能繞過代理直連，第 1 層就白做；能偽造 IP，第 5、7 層就失準 | [client-ip.md](references/client-ip.md) |
| 3 | 程式內 GeoIP（備案） | 沒有可設定的代理、或要多一層時才做 | [app-geoip.md](references/app-geoip.md) |
| 4 | 密碼 → 第二步（TOTP 或 passkey）；passkey 也可以單獨登入 | 台灣境內的人仍連得到登入頁，真正的防線在這裡 | [two-step-login.md](references/two-step-login.md)、[passkeys.md](references/passkeys.md) |
| 5 | 連續失敗鎖定，所有步驟共用一個計數 | 擋猜密碼，也擋「密碼對了再猜六位數」 | [two-step-login.md](references/two-step-login.md) |
| 6 | 登入後的 session：期限、作廢、Cookie 屬性、安全標頭 | 登入成果只存在 Cookie 裡，要防被偷、被嵌入、被跨站使用 | [session-and-headers.md](references/session-and-headers.md) |
| 7 | 每次登入事件寫一行紀錄，失敗帶原因 | 出事後才查得到誰、何時、從哪、為什麼沒成功 | [session-and-headers.md](references/session-and-headers.md) |

## 貫穿各層的規則

- **一個真實 IP**：每個請求只在入口算一次真實 IP（第 2 層），鎖定、GeoIP、紀錄都用這個值，不各自讀標頭。
- **寧可擋錯**：GeoIP 資料庫不在、讀不懂、查不到國家時，非內網一律擋；設定檔讀不出來時，登入失敗而不是放行。
- **秘密不落地成明文**：密碼存雜湊；session token、登記碼、一次性 token 只存 SHA-256；TOTP 金鑰檔只有擁有者可讀；任何秘密都不寫進紀錄、錯誤訊息或回應。
- **一次性的東西只能用一次**：TOTP 每一組數字、WebAuthn 每個挑戰值、每個登記 token，用掉就作廢，並且在同一個鎖或交易裡檢查與寫回。
- **登入前的頁面什麼都不透露**：不帶主機路徑、內部網址、帳號是否存在、密碼對不對（第二步沒設好時，在比對密碼之前就回錯）。

## 常見陷阱

這些都是實際踩過、照常理會做錯的地方；詳細做法在對應的參考檔。

- Nginx Proxy Manager 的全域設定會相信內網送來的 `X-Real-IP` 並改寫來源：國家與內網判斷要用 `$realip_remote_addr`，該站加 `set_real_ip_from unix:;`。
- 國家限制只寫在 `location /` 會被繞過：NPM 的 Cache Assets 會另加比對 `.js`、`.png` 的 location。擋在 `server` 層級。
- 只刪 `.mmdb` 而留著引用它的 `geoip2` 設定，`nginx -t` 會失敗，代理一重啟整台機器的網站都起不來。
- uvicorn 預設開著 proxy headers，並相信 `127.0.0.1`、`::1` 送來的 `X-Forwarded-For`：用 `--no-proxy-headers` 啟動，自己判斷。
- adapter-node 送靜態檔不經過 `hooks.server.ts`；沒設 `PROTOCOL_HEADER` 時 `event.url.protocol` 一律是 https。
- scrypt 用 N=2^15、r=8 時，Python 與 Node 都要明確傳 `maxmem`，預設上限太小會直接丟錯。
- 壞掉的 `.mmdb` 讓 Python `geoip2` 丟 `maxminddb.InvalidDatabaseError`（屬於 `RuntimeError`），不是 `OSError`。
- 密碼對了就清除失敗計數，攻擊者每猜一次 TOTP 前先送一次正確密碼，就永遠不會被鎖。
- `pyotp` 的 `verify()` 只回答對錯，不告訴你是哪一步，做不到「每組只能用一次」。
- py_webauthn 的 `require_user_verification` 預設 `False`，SimpleWebAuthn 預設 `true`：免密碼登入一定要明確開。
- `SameSite=Strict` 的登入 Cookie 在從別的網站或主畫面捷徑打開時不會送出，看起來像被登出。
- 清除 Cookie 時沒帶 `Secure`（設定時有帶），瀏覽器會忽略這個清除。
- 同一個主機名稱上的兩個服務用同名 Cookie 會互相蓋掉登入（Cookie 不分 port）。
- 已登入時的 passkey 登記失敗回 401，前端多半當成「已登出」而重新載入。

## 套用時

1. 決定第 1 層能不能在代理做；能的話第 3 層可以不做。
2. 只讀這次要做或要審的那幾層的參考檔（上表最右欄），不必全部讀。只做第 4 層以後也要讀 [client-ip.md](references/client-ip.md)：鎖定與紀錄用它算的真實 IP。參考檔裡 Node 與 FastAPI 片段並列，只看專案用的那種。
3. 照各檔的規則實作。片段都執行驗證過，邏輯照用，只把儲存換成專案自己的（資料庫、Redis）。
4. 跑 [checklist.md](references/checklist.md) 的每一項，全部打勾才算完成；沒做的項目在交付說明裡寫出原因。
