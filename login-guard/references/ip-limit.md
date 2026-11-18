# 台灣 IP 限制與真實 IP

三件事，依序：代理擋國家（第 1 層）、程式只信代理（第 2 層）、程式內 GeoIP 備案（第 3 層）。

只放台灣能擋的有限：境內的人、用台灣 VPN 的人都到得了登入頁。它的用處是把大量國外掃描擋在門外，真正的防線仍是兩步登入。

## 1. 反向代理擋國家

規則與理由：

- **用實際 TCP 來源判斷國家**，nginx 是 `$realip_remote_addr`，不是 `$remote_addr`。很多代理的全域設定（例如 Nginx Proxy Manager 預設）會相信內網或 Docker 網段送來的 `X-Real-IP` 並改寫 `$remote_addr`，內網的人就能自稱任何 IP。在這個站的 `server` 裡寫 `set_real_ip_from unix:;`，取代繼承來的信任清單。
- **在 `server` 層級擋**（`if (...) { return 403; }`），不要只寫在 `location /`。管理介面自己加的 location（例如 NPM 的「Cache Assets」會加一個比對 `.js`、`.css`、`.png` 的 regex location）會繞過 `location /`，國外照樣拿得到靜態檔，甚至打到 `/api/x.js` 這種路徑。
- **轉給程式的 `X-Forwarded-For` 覆寫成實際來源**（`proxy_set_header X-Forwarded-For $realip_remote_addr;`），不要用 `$proxy_add_x_forwarded_for` 把訪客送來的值接在後面。程式就只會看到一個、而且是真的位址。
- **沒有資料庫時只有內網進得來**：國家變數預設空字串，資料庫驗證過才由更新程式寫出啟用查詢的 include。`geoip2` 指令遇到不存在的檔案會讓 `nginx -t` 失敗，代理重啟時整台機器上的網站都起不來；所以絕不能只刪 `.mmdb` 而留著引用它的 include，要先刪 include 或一起刪。
- **內網例外只寫你自己的網段**，寫死整個 10/8、172.16/12、192.168/16 會把同網段的容器、VPN 也放進來。
- 代理上還有別的網站時，變數名稱加前綴，只有這個站引用，其他站不受影響。

### nginx（含 ngx_http_geoip2_module）

已在 nginx 1.26 + ngx_http_geoip2_module 實測：國外來源有無資料庫都 403、允許的國家 200、偽造的 `X-Forwarded-For`／`X-Real-IP` 被換成實際來源。

```nginx
# --- http {} 層級 ---
# 國家：裝好驗證過的資料庫之前是空的，所以只有內網規則能放行（寧可擋錯）。
map "" $login_country { default ""; }
# 更新程式在資料庫驗證過後才寫這個檔；[.] 讓檔案不存在也合法。
include /etc/nginx/geoip/country[.]conf;

# $realip_remote_addr 是 TCP 來源，不受 X-Real-IP / X-Forwarded-For 改寫。
geo $realip_remote_addr $login_lan {
    default          0;
    127.0.0.0/8      1;
    192.168.50.0/24  1;   # 換成你自己的內網
}

map "$login_lan:$login_country" $login_allowed {
    default 0;
    "~^1:"  1;
    "0:TW"  1;
}

server {
    server_name admin.example.com;
    # 這個站不相信任何訪客送來的 X-Real-IP，即使全域設定相信。
    set_real_ip_from unix:;

    # server 層級，所有 location（含介面自己加的）都經過這裡。
    if ($login_allowed = 0) {
        return 403;
    }

    location / {
        proxy_set_header X-Forwarded-For   $realip_remote_addr;
        proxy_set_header X-Real-IP         $realip_remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host              $host;
        proxy_pass http://192.0.2.20:8000;
    }
}
```

更新程式寫出的 `/etc/nginx/geoip/country.conf`：

```nginx
geoip2 /etc/nginx/geoip/GeoLite2-Country.mmdb {
    $login_country source=$realip_remote_addr country iso_code;
}
```

### Nginx Proxy Manager

- 先確認映像檔有模組：`ls /usr/lib/nginx/modules/ | grep geoip2`。
- `load_module` 放 `data/nginx/custom/root_top.conf`；上面 http 層級的 `map`、`geo`、`include` 放 `data/nginx/custom/http_top.conf`。這兩個檔 NPM 重建設定時會保留。
- `set_real_ip_from`、`if` 與 `location /` 放在該站的 Advanced 欄位；Advanced 裡寫了 `location /` 時，NPM 不再產生自己的，所以要把它原本的 `proxy_set_header` 也搬進來。
- 關掉該站的 Cache Assets，或確認 `if` 在 server 層級。改完用 NPM 介面再存一次該站，確認規則還在。

### 資料庫來源與每日更新

- **預設用 MaxMind 官方 GeoLite2 Country**：要免費帳號與授權碼，用官方 `geoipupdate` 下載（本身會原子替換），跑完後重新載入 nginx 或程式。
- 不想註冊帳號時，才用第三方轉載的 GeoLite2 `.mmdb`（例如 GitHub releases 上的鏡像）配下面的更新程式。它不是官方，對方停更或下載失敗時會一直用舊資料，國家判斷慢慢不準，所以失敗一定要留紀錄。
- 每天一次，用 systemd timer 或 cron；排程寫明時區（UTC）並加隨機延遲，避免整點一起下載。

更新程式（下載 → 驗證 → 原子替換 → 重新載入；任何一步失敗都保留舊檔、exit 1、錯誤寫到 stderr 進 journal）。已實測：下載 404、壞檔、正常、未變更、正常後再給壞檔（舊檔保留）。

```sh
#!/bin/sh
set -eu
URL="${GEOIP_URL:?set GEOIP_URL to a URL serving a plain .mmdb}"
DIR="${GEOIP_DIR:-/etc/nginx/geoip}"
CHECK_IP="${GEOIP_CHECK_IP:-8.8.8.8}"     # 資料庫一定查得到的公開位址
DB="$DIR/GeoLite2-Country.mmdb"
tmp=$(mktemp "$DIR/.download.XXXXXX")     # 同一個檔案系統，mv 才是原子的
trap 'rm -f "$tmp"' EXIT

curl -fsSL --max-time 120 -o "$tmp" "$URL" || { echo "FAILED: download" >&2; exit 1; }
mmdblookup --file "$tmp" --ip "$CHECK_IP" country iso_code >/dev/null 2>&1 \
    || { echo "FAILED: not a usable country database" >&2; exit 1; }
if [ -f "$DB" ] && cmp -s "$tmp" "$DB"; then echo "unchanged"; exit 0; fi
chmod 644 "$tmp"
mv "$tmp" "$DB"
# 啟用查詢的 include 只在有了有效資料庫之後才寫。
[ -f "$DIR/country.conf" ] || cat > "$DIR/country.conf" <<CONF
geoip2 $DB {
    \$login_country source=\$realip_remote_addr country iso_code;
}
CONF
nginx -t && nginx -s reload
echo "updated"
```

`mmdblookup` 來自 libmaxminddb（Debian `mmdb-bin`、Alpine `libmaxminddb`）；查不到 `CHECK_IP` 時它的結束碼不是 0，所以壞檔與空資料庫都會被擋下。

## 2. 程式只接受信任來源，真實 IP 只信代理

規則與理由：

- **允許連線清單**（看 socket 位址，IP 或 CIDR）：不在清單上就 403，在任何路由之前，包括靜態檔與框架自己的錯誤頁。沒設定時只放本機，更新後才不會意外對外開放。能繞過代理直連，代理上的國家限制與真實 IP 都沒有意義。
- **信任代理清單**：socket 位址在清單上，才讀 `X-Forwarded-For`。由右往左取第一個不是信任代理的位址（最右邊是離程式最近的代理加上的，左邊的可能是訪客自己帶的）；全是信任代理時取最左邊；任何一項不是 IP 就整串不用，改用 socket 位址。`X-Real-IP`、`CF-Connecting-IP` 一律不讀：代理沒覆寫時，訪客送什麼就是什麼。
- **HTTPS 只信代理說的**：socket 位址是信任代理且 `X-Forwarded-Proto: https` 才算。它決定 Cookie 的 `Secure`、HSTS、passkey 能不能用。
- 雙協定 socket 把 IPv4 報成 `::ffff:a.b.c.d`，比對前先轉回 IPv4。
- 清單裡有不是 IP／CIDR 的項目，啟動時就失敗，不要默默略過。
- 這兩份清單與真實 IP 只在入口算一次，放進 request 狀態，鎖定、GeoIP、紀錄都讀它。

### Node（TypeScript）

```ts
// client-ip.ts
import { BlockList, isIP } from 'node:net';

export const plainIp = (ip: string) => /^::ffff:(\d+\.\d+\.\d+\.\d+)$/i.exec(ip)?.[1] ?? ip;

/** "192.0.2.10, 10.0.0.0/8, ::1" -> 成員判斷。項目不對就丟錯，啟動時失敗。 */
export function ipList(text: string): (ip: string) => boolean {
	const list = new BlockList();
	for (const entry of text.split(/[\s,]+/).filter(Boolean)) {
		const [address, prefix, ...rest] = entry.split('/');
		const family = isIP(address);
		const bits = family === 4 ? 32 : 128;
		const length = prefix === undefined ? bits : /^\d+$/.test(prefix) ? Number(prefix) : NaN;
		if (!family || rest.length || !(length >= 0 && length <= bits)) throw new Error(`not an IP or CIDR: ${entry}`);
		list.addSubnet(address, length, family === 4 ? 'ipv4' : 'ipv6');
	}
	return (ip) => {
		const address = plainIp(ip);
		const family = isIP(address);
		return family !== 0 && list.check(address, family === 4 ? 'ipv4' : 'ipv6');
	};
}

export function clientIp(peer: string, forwardedFor: string | null, trusted: (ip: string) => boolean): string {
	const own = plainIp(peer);
	if (!forwardedFor || !trusted(own)) return own;
	const hops = forwardedFor.split(',').map((hop) => plainIp(hop.trim()));
	if (hops.some((hop) => !isIP(hop))) return own;
	for (let i = hops.length - 1; i >= 0; i--) if (!trusted(hops[i])) return hops[i];
	return hops[0];
}

export const viaHttps = (peer: string, forwardedProto: string | null, trusted: (ip: string) => boolean) =>
	trusted(peer) && forwardedProto?.trim().toLowerCase() === 'https';
```

SvelteKit（adapter-node）接法：

- adapter-node 自己送出的靜態檔不經過 `hooks.server.ts`，所以允許清單要在更外面擋：用 adapter-node 的自訂伺服器，先檢查再交給 `handler`。
- 不要設 `ADDRESS_HEADER`、`XFF_DEPTH`，`getClientAddress()` 才是 socket 位址。`event.url.protocol` 不可信（沒設 `PROTOCOL_HEADER`／`ORIGIN` 時 adapter-node 一律當 https），改用 `viaHttps`。
- `hooks.server.ts` 再設一次標頭：SvelteKit 寫出的同名標頭會蓋掉自訂伺服器先放的。`handle` 裡自己 `throw redirect()` 的回應不經過 `resolve` 之後的程式，要標頭就直接 `return new Response(null, { status: 303, headers: { location } })`。`vite dev` 不經自訂伺服器，靠 `handle` 這段擋。

```js
// server.js：取代 `node build`。直接匯入 .ts 要 Node 22.6 以上加 --experimental-strip-types（23.6 起不用加）
import http from 'node:http';
import { handler } from './build/handler.js';
import { ipList, viaHttps } from './src/lib/server/client-ip.ts';
import { securityHeaders } from './src/lib/server/security-headers.ts'; // 見 session-and-headers.md

const allowedPeers = ipList(process.env.ALLOWED_PEERS || '127.0.0.1, ::1');
const trustedProxies = ipList(process.env.TRUSTED_PROXIES || '');

http.createServer((req, res) => {
	const peer = req.socket.remoteAddress ?? '';
	const https = viaHttps(peer, req.headers['x-forwarded-proto'] ?? null, trustedProxies);
	for (const [name, value] of securityHeaders(https)) res.setHeader(name, value);
	if (!allowedPeers(peer)) {
		res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' }).end('Forbidden');
		return;
	}
	handler(req, res);
}).listen(Number(process.env.PORT || 3000), process.env.HOST || '127.0.0.1');
```

```ts
// src/hooks.server.ts（SvelteKit 3）
import type { Handle } from '@sveltejs/kit/hooks';
import { clientIp, ipList, viaHttps } from '#lib/server/client-ip.ts';
import { securityHeaders } from '#lib/server/security-headers.ts';

const allowedPeers = ipList(process.env.ALLOWED_PEERS || '127.0.0.1, ::1');
const trustedProxies = ipList(process.env.TRUSTED_PROXIES || '');

export const handle: Handle = async ({ event, resolve }) => {
	const peer = event.getClientAddress(); // ADDRESS_HEADER 沒設時就是 socket 位址
	const https = viaHttps(peer, event.request.headers.get('x-forwarded-proto'), trustedProxies);
	event.locals.clientIp = clientIp(peer, event.request.headers.get('x-forwarded-for'), trustedProxies);
	event.locals.https = https;
	const response = allowedPeers(peer) ? await resolve(event) : new Response('Forbidden', { status: 403 });
	for (const [name, value] of securityHeaders(https)) response.headers.set(name, value);
	return response;
};
```

`src/app.d.ts` 的 `App.Locals` 加上 `clientIp: string; https: boolean`。SvelteKit 2 的寫法差在兩處：`import type { Handle } from '@sveltejs/kit'`，以及用 `$lib/server/...` 匯入。

### FastAPI（Python）

uvicorn 預設開著 `proxy_headers`，並相信 `127.0.0.1`、`::1` 送來的 `X-Forwarded-For`（環境變數 `FORWARDED_ALLOW_IPS`），`request.client.host` 可能已經被改寫。用 `uvicorn --no-proxy-headers` 啟動，讓 `request.client.host` 一定是 socket 位址，規則只在下面這一處。

```python
# client_ip.py
import ipaddress
from collections.abc import Callable


def ip_list(text: str) -> Callable[[str], bool]:
    """"192.0.2.10, 10.0.0.0/8, ::1" -> 成員判斷。項目不對就丟 ValueError，啟動時失敗。"""
    networks = [ipaddress.ip_network(e, strict=False) for e in text.replace(",", " ").split()]

    def contains(ip: str) -> bool:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(address in n for n in networks)

    return contains


def client_ip(peer: str, forwarded_for: str | None, trusted: Callable[[str], bool]) -> str:
    if not forwarded_for or not trusted(peer):
        return peer
    hops = [h.strip() for h in forwarded_for.split(",")]
    for hop in hops:
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer
    for hop in reversed(hops):
        if not trusted(hop):
            return hop
    return hops[0]


def via_https(peer: str, forwarded_proto: str | None, trusted: Callable[[str], bool]) -> bool:
    return trusted(peer) and (forwarded_proto or "").strip().lower() == "https"
```

```python
# guard.py：中介層在路由之前執行，同一個 app 掛的 StaticFiles 也經過它
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .client_ip import client_ip, ip_list, via_https
from .geoip import CountryGate  # 第 3 層，不做就拿掉
from .security_headers import security_headers  # 見 session-and-headers.md

TRUSTED_PROXIES = ip_list("192.0.2.10")
ALLOWED_PEERS = ip_list("127.0.0.1, ::1, 192.0.2.10")
gate = CountryGate("/var/lib/geoip/GeoLite2-Country.mmdb", {"TW"}, ip_list("127.0.0.0/8, ::1, 192.168.50.0/24"))


def install_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        peer = request.client.host if request.client else ""
        https = via_https(peer, request.headers.get("x-forwarded-proto"), TRUSTED_PROXIES)
        ip = client_ip(peer, request.headers.get("x-forwarded-for"), TRUSTED_PROXIES)
        request.state.client_ip, request.state.https = ip, https
        if not ALLOWED_PEERS(peer) or not gate.allows(ip):
            response = PlainTextResponse("Forbidden", status_code=403)
        else:
            response = await call_next(request)
        for name, value in security_headers(https):
            response.headers.setdefault(name, value)
        return response
```

## 3. 程式內 GeoIP（備案）

沒有能設定的代理，或想多一層時才做。規則與理由：

- 判斷用第 2 層算出的真實 IP。
- **例外清單先比**：本機與你自己的內網段（從設定讀），不查資料庫。
- **查不到國家就擋**（`AddressNotFoundError`、不是 IP）。
- **沒有資料庫就只放例外清單**。資料庫壞掉時「全部放行」等於限制失效而沒人發現；真要選放行，寫成明確的設定與紀錄，不要當預設。
- **資料庫被替換後重新開啟**：更新程式原子替換檔案後，程式要重開 reader（例如每小時比一次檔案修改時間，或收到訊號時）。重開失敗就保留舊的 reader。用上面第 1 層的更新程式時，拿掉寫 `country.conf` 與重新載入 nginx 的最後幾行，改成通知程式。
- 被擋時寫一行紀錄，帶真實 IP 與查到的國家碼。

### Node：`@maxmind/geoip2-node`

```ts
import { Reader, type ReaderModel } from '@maxmind/geoip2-node';

let reader: ReaderModel | null = null;

/** 開啟或在檔案替換後重開；失敗時保留舊的 reader（第一次就失敗則沒有 reader，只放例外清單）。 */
export async function loadCountryDb(path: string): Promise<boolean> {
	try {
		reader = await Reader.open(path);
		return true;
	} catch (error) {
		console.error(`GeoIP database unusable: ${(error as Error).message}`);
		return false;
	}
}

export function countryAllowed(ip: string, allowed: Set<string>, exempt: (ip: string) => boolean): boolean {
	if (exempt(ip)) return true;
	if (!reader) return false;
	try {
		return allowed.has(reader.country(ip).country?.isoCode ?? '');
	} catch {
		return false; // AddressNotFoundError、不是 IP
	}
}
```

### Python：`geoip2`

```python
# geoip.py
import logging
from collections.abc import Callable

import geoip2.database
import geoip2.errors
import maxminddb

logger = logging.getLogger(__name__)


class CountryGate:
    def __init__(self, path: str, allowed: set[str], exempt: Callable[[str], bool]):
        self.path, self.allowed, self.exempt = path, allowed, exempt
        self.reader: geoip2.database.Reader | None = None
        self.reload()

    def reload(self) -> None:
        """啟動時與更新程式替換檔案後呼叫；開不了就保留舊的 reader。"""
        try:
            new = geoip2.database.Reader(self.path)
        except (OSError, maxminddb.InvalidDatabaseError) as error:  # 不存在、不是 mmdb
            logger.error("geoip_unusable", extra={"error": type(error).__name__})
            return
        old, self.reader = self.reader, new
        if old:
            old.close()

    def allows(self, ip: str) -> bool:
        if self.exempt(ip):
            return True
        if self.reader is None:
            return False
        try:
            return self.reader.country(ip).country.iso_code in self.allowed
        except (geoip2.errors.AddressNotFoundError, ValueError):
            return False
```

以上 Node 與 Python 片段已用 MaxMind 官方測試資料庫（`GeoIP2-Country-Test.mmdb`）實測：沒有資料庫時內網放行、外部擋；查不到國家擋；替換失敗保留舊資料。
