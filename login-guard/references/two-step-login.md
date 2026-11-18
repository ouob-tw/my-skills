# 密碼＋TOTP 兩步登入與連續失敗鎖定

密碼對了只打開一個 5 分鐘的第二步，第二步（TOTP 或 passkey，passkey 見 [passkeys.md](passkeys.md)）通過才發登入 Cookie。所有步驟共用一個失敗計數。

## 第一步：密碼

- **存雜湊不存明文**：預設 scrypt（N=2^15、r=8、p=1，16 位元組隨機鹽，32 位元組結果），存成 `scrypt$N$r$p$鹽$結果`（鹽與結果用 base64），參數跟著存，日後調高也認得舊的；專案已經用 argon2id 就沿用。比對時用存下的參數重算，再用固定時間比較（`hmac.compare_digest`、`timingSafeEqual`）。
- **`maxmem` 一定要明確給 `128 * N * r * 2`**：Python 與 Node 的預設上限都比 N=2^15、r=8 需要的小，不給就直接丟錯（Node 是 `memory limit exceeded`）。

```python
digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=128 * N * R * 2, dklen=32)
```

```ts
// Node：用非同步版，免得卡住事件迴圈
const scryptAsync = promisify(scrypt) as (password: string, salt: Buffer, length: number, options: ScryptOptions) => Promise<Buffer>;
const digest = await scryptAsync(password, salt, 32, { N, r: R, p: P, maxmem: 128 * N * R * 2 });
```

- **先確認第二步設好了，再比對密碼**：沒有任何第二步時直接回 409 `no_second_step`，不比對密碼，免得這個回應透露密碼對不對。
- **密碼對了不發登入 Cookie**：只開第二步。第二步的 token 是 32 位元組亂數，伺服器只存它的 SHA-256 與到期時間（5 分鐘）；Cookie 設 `HttpOnly`、`SameSite=Strict`、`Path=/api/login`（只有登入端點收得到）、HTTPS 時 `Secure`、`Max-Age=300`。存在記憶體也可以，重啟就要重輸密碼。

## 第二步：TOTP

規則與理由：

- **照驗證器 App 的預設**：RFC 6238、HMAC-SHA1、6 位數、30 秒。改了其他值，部分 App 會默默算出不同的數字。
- **前後各容許一步**（共 90 秒），手機時鐘差一點也能用；不要開更大。
- **金鑰 20 位元組亂數**（base32 後 32 字元），由伺服器產生。
- **登記要先確認**：新金鑰先放在待確認狀態，顯示 QR code 與文字版金鑰，使用者輸入一組當下的數字對了才存成正式金鑰，並把這組數字的步數記成「已用過」，它不能再拿來登入。QR code 在自己的伺服器或瀏覽器裡產生，不要把 `otpauth://` 網址送到外部的 QR 服務：那就是金鑰本身。
- **誰能登記**：已登入的 session 在設定裡登記，而且要再輸入一次密碼（更換時另要舊的 TOTP 數字）；只有一個管理者的服務也可以只開放主機指令登記。只知道密碼的人不能自己登記第二步。
- **每組數字只能用一次**：記住最後一次登入用掉的步數（`last_step`），同一組或更早步數的數字一律拒絕。讀出金鑰、比對、寫回 `last_step` 要在同一個交易或鎖裡，兩個同時送來的請求才不會都用掉同一組；更換或清除金鑰也拿同一個鎖，比對中的登入才不會把舊金鑰寫回去。
- **更換後舊金鑰的數字立刻失效**；改密碼、更換或清除金鑰時作廢其他 session，見 [session-and-headers.md](session-and-headers.md)。
- **金鑰存放**：資料庫欄位加密，或檔案權限只有擁有者可讀（600）。讀檔失敗的錯誤訊息不要引用檔案內容（JSON 解析錯誤常會把內容印出來）。
- 數字錯誤與密碼錯誤一樣計入鎖定。

### Node（`node:crypto`，不需套件）

```ts
// totp.ts
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const STEP_SECONDS = 30;
const DIGITS = 6;

export function base32Encode(bytes: Buffer): string {
	let bits = 0, value = 0, out = '';
	for (const byte of bytes) {
		value = (value << 8) | byte;
		bits += 8;
		while (bits >= 5) { out += B32[(value >>> (bits - 5)) & 31]; bits -= 5; }
	}
	return bits > 0 ? out + B32[(value << (5 - bits)) & 31] : out;
}

export function base32Decode(text: string): Buffer {
	const out: number[] = [];
	let bits = 0, value = 0;
	for (const char of text.toUpperCase().replace(/=+$/, '')) {
		const index = B32.indexOf(char);
		if (index < 0) throw new Error('not base32');
		value = (value << 5) | index;
		bits += 5;
		if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; }
	}
	return Buffer.from(out);
}

export const newTotpSecret = () => base32Encode(randomBytes(20));

export function codeAt(secret: string, step: number, digits = DIGITS): string {
	const counter = Buffer.alloc(8);
	counter.writeBigUInt64BE(BigInt(step));
	const mac = createHmac('sha1', base32Decode(secret)).update(counter).digest();
	const offset = mac[mac.length - 1] & 15;
	return String((mac.readUInt32BE(offset) & 0x7fffffff) % 10 ** digits).padStart(digits, '0');
}

export const stepAt = (unixSeconds: number) => Math.floor(unixSeconds / STEP_SECONDS);

/** 數字屬於哪一步（現在或前後一步），都不是就 null。空白忽略。登記確認時把回傳的步數存成 lastStep，確認用的數字就不能再登入。 */
export function matchingStep(secret: string, code: string, unixSeconds: number): number | null {
	const digits = code.replace(/\s/g, '');
	if (!/^\d{6}$/.test(digits)) return null;
	const now = stepAt(unixSeconds);
	for (let step = now - 1; step <= now + 1; step++) {
		if (timingSafeEqual(Buffer.from(codeAt(secret, step)), Buffer.from(digits))) return step;
	}
	return null;
}

export function otpauthUrl(secret: string, issuer: string, account: string): string {
	const label = `${encodeURIComponent(issuer)}:${encodeURIComponent(account)}`;
	return `otpauth://totp/${label}?secret=${secret}&issuer=${encodeURIComponent(issuer)}&algorithm=SHA1&digits=${DIGITS}&period=${STEP_SECONDS}`;
}

/** 登入：數字對而且比用過的新，回傳新的 lastStep，否則 null。讀寫要在同一個交易或鎖裡。 */
export function useCode(stored: { secret: string; lastStep: number }, code: string, unixSeconds: number): number | null {
	const step = matchingStep(stored.secret, code, unixSeconds);
	return step !== null && step > stored.lastStep ? step : null;
}
```

### Python（`pyotp`）

`pyotp.TOTP.verify()` 只回答對或錯，不告訴你是哪一步，做不到「每組只能用一次」，所以自己找步數：

```python
# totp.py
import hmac
import time

import pyotp

STEP = 30


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """數字屬於哪一步，都不是就 None。登記確認時把回傳的步數存成 last_step。"""
    digits = "".join(code.split())
    if len(digits) != 6 or not digits.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int((time.time() if now is None else now) // STEP)
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), digits):
            return step
    return None


def use_code(secret: str, last_step: int, code: str, now: float | None = None) -> int | None:
    """登入：數字對而且比用過的新，回傳新的 last_step。讀寫在同一個交易裡（SELECT ... FOR UPDATE）。"""
    step = matching_step(secret, code, now)
    return step if step is not None and step > last_step else None
```

## 登入流程與失敗計數的呼叫順序

每個會比對秘密的端點（密碼、TOTP、passkey 驗證）都照下面程式的順序呼叫 `limit`（四個方法見下一節）。拿 passkey 挑戰值的 options 端點不證明任何事，不呼叫 `limit`。

FastAPI 寫法，儲存換成了占位函式（`totp_configured`、`load_password_hash`、`db.transaction` 等）：

```python
import hashlib
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

STEP_COOKIE, STEP_PATH, STEP_SECONDS = "app_step", "/api/login", 5 * 60
router = APIRouter()
limit = LoginLimit()
open_steps: dict[str, float] = {}  # sha256(token) -> 到期時間；正式環境用 Redis 或資料庫加 TTL


def error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


def locked(seconds: int) -> JSONResponse:
    return JSONResponse({"error": "locked", "retryAfterSeconds": seconds}, status_code=429, headers={"Retry-After": str(seconds)})


def step_key(request: Request) -> str | None:
    token = request.cookies.get(STEP_COOKIE)
    if not token:
        return None
    key = hashlib.sha256(token.encode()).hexdigest()
    return key if open_steps.get(key, 0) > time.time() else None


@router.post("/api/login")
async def password_step(request: Request):
    body = await request.json()
    ip = request.state.client_ip  # 入口算好的真實 IP（client-ip.md）
    if wait := limit.admit(ip):
        return locked(wait)
    if not totp_configured():
        limit.refund(ip)
        return error(409, "no_second_step")
    if not check_password(str(body.get("password", "")), load_password_hash()):
        wait = limit.failed(ip)
        return locked(wait) if wait else error(401, "wrong_password")
    limit.refund(ip)  # 只有密碼對：不加也不清
    token = secrets.token_urlsafe(32)
    open_steps[hashlib.sha256(token.encode()).hexdigest()] = time.time() + STEP_SECONDS
    response = JSONResponse({"secondStep": ["totp"], "secondsLeft": STEP_SECONDS})
    response.set_cookie(STEP_COOKIE, token, max_age=STEP_SECONDS, path=STEP_PATH,
                        httponly=True, samesite="strict", secure=request.state.https)
    return response


@router.post("/api/login/totp")
async def totp_step(request: Request):
    body = await request.json()
    ip = request.state.client_ip
    if wait := limit.admit(ip):
        return locked(wait)
    key = step_key(request)
    if key is None:
        limit.refund(ip)
        return error(401, "second_step_expired")
    with db.transaction():  # SELECT ... FOR UPDATE 到 UPDATE 之間
        totp = load_totp_for_update()
        new_step = use_code(totp.secret, totp.last_step, str(body.get("code", "")))
        if new_step is not None:
            save_last_step(new_step)
    wait = limit.succeeded(ip) if new_step is not None else limit.failed(ip)
    if wait:
        return locked(wait)
    if new_step is None:
        return error(401, "wrong_code")
    del open_steps[key]
    response = JSONResponse({"loggedIn": True})
    response.delete_cookie(STEP_COOKIE, path=STEP_PATH, httponly=True, samesite="strict", secure=request.state.https)
    create_session_and_set_cookie(response, request, second_step="totp")  # session-and-headers.md
    return response
```

SvelteKit 的 `+server.ts` 照同樣順序寫：`cookies.set(STEP_COOKIE, token, { path: '/api/login', httpOnly: true, sameSite: 'strict', secure: locals.https, maxAge: 300 })`，真實 IP 與 HTTPS 從 `locals` 讀。

## 連續失敗鎖定

規則與理由：

- **以真實 IP 計數**（入口算好的那個）。多使用者的服務另加「每個帳號」的計數，但帳號那邊用逐步變慢而不是硬鎖，免得別人故意輸錯把正主鎖在門外。
- **所有步驟共用一個計數**：密碼錯、TOTP 錯、passkey 驗證失敗、登記時密碼或登記碼錯，都算一次。分開算，猜六位數就有自己的 5 次。
- **只有整個登入成功、要發登入 Cookie 時才清除**。密碼對但還沒過第二步用 `refund`：不加也不清。
- **先 `admit` 再比對，並把進行中的嘗試算進去**：同時送 50 個請求的人，也只拿到剩下的次數。
- **不算次數的情況用 `refund`**：第二步過期、伺服器讀不到設定檔。`refund` 只能接在 `admit` 之後；passkey 的 options 端點不呼叫 `limit`，也就不 `refund`。
- **重啟不清除**：失敗次數與鎖定到期時間存到資料庫、Redis，或權限 600 的檔案（寫暫存檔再 rename）。進行中的嘗試只在記憶體。
- 追蹤的來源數設上限，滿了先丟掉沒鎖、也沒有進行中嘗試的最舊來源。
- 被鎖時回 429 加 `Retry-After`；鎖定開始時寫一行 `login_locked` 紀錄（只寫一次，帶當時的事件），見 [session-and-headers.md](session-and-headers.md)。
- 門檻例如 5 次、鎖 15 分鐘；做成設定，測試時可以調短。

Python（記憶體版；正式環境把 `failures`、`locked_until` 存起來）：

```python
import time
from dataclasses import dataclass

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


@dataclass
class Source:
    failures: int = 0
    pending: int = 0  # 已 admit、還沒結束的嘗試
    locked_until: float = 0.0


class LoginLimit:
    """每次嘗試先 admit()，再恰好呼叫一次 failed() / succeeded() / refund()。回傳要等的秒數，0 表示繼續。"""

    def __init__(self, now=time.time):
        self.now, self.sources = now, {}

    def _wait(self, s: Source) -> int:
        return max(1, int(s.locked_until - self.now() + 0.999)) if s.locked_until > self.now() else 0

    def _lock(self, s: Source) -> int:
        s.failures, s.locked_until = 0, self.now() + LOCK_SECONDS
        return self._wait(s)  # 在這裡寫 login_locked 紀錄，一次

    def admit(self, ip: str) -> int:
        s = self.sources.setdefault(ip, Source())
        if wait := self._wait(s):
            return wait
        if s.failures + s.pending >= MAX_FAILURES:  # 同時送一堆也拿不到更多次
            return self._lock(s)
        s.pending += 1
        return 0

    def failed(self, ip: str) -> int:
        s = self.sources[ip]
        s.pending -= 1
        if wait := self._wait(s):
            return wait
        s.failures += 1
        return self._lock(s) if s.failures >= MAX_FAILURES else 0

    def succeeded(self, ip: str) -> int:
        """只在整個登入通過、要發 Cookie 時呼叫。"""
        s = self.sources[ip]
        s.pending -= 1
        if wait := self._wait(s):
            return wait  # 同時進行的其他嘗試已經把它鎖住：照樣拒絕
        s.failures = 0
        return 0

    def refund(self, ip: str) -> None:
        self.sources[ip].pending -= 1
```

Node 版照同樣的四個方法寫；`Map` 存來源，存檔用 `writeFileSync` 暫存檔（`mode: 0o600`）再 `renameSync`。
