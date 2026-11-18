# 第 2 層：程式只接受信任來源，真實 IP 只信代理

規則與理由：

- **允許連線清單**（看 socket 位址，IP 或 CIDR）：不在清單上就 403，在任何路由之前，包括靜態檔與框架自己的錯誤頁。沒設定時只放本機，更新後才不會意外對外開放。能繞過代理直連，代理上的國家限制與真實 IP 都沒有意義。
- **信任代理清單**：socket 位址在清單上，才讀 `X-Forwarded-For`。由右往左取第一個不是信任代理的位址（最右邊是離程式最近的代理加上的，左邊的可能是訪客自己帶的）；全是信任代理時取最左邊；任何一項不是 IP 就整串不用，改用 socket 位址。`X-Real-IP`、`CF-Connecting-IP` 一律不讀：代理沒覆寫時，訪客送什麼就是什麼。
- **HTTPS 只信代理說的**：socket 位址是信任代理且 `X-Forwarded-Proto: https` 才算。它決定 Cookie 的 `Secure`、HSTS、passkey 能不能用。
- 雙協定 socket 把 IPv4 報成 `::ffff:a.b.c.d`，比對前先轉回 IPv4。
- 清單裡有不是 IP／CIDR 的項目，啟動時就失敗，不要默默略過。
- 這兩份清單與真實 IP 只在入口算一次，放進 request 狀態，鎖定、GeoIP、紀錄都讀它。

## Node（TypeScript）

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
- `hooks.server.ts` 再設一次標頭：SvelteKit 寫出的同名標頭會蓋掉自訂伺服器先放的。回應已經有 CSP 時用 `append` 加成第二條政策，`set` 會把它（例如上傳檔案的 `sandbox`）換成較寬鬆的預設值。`handle` 裡自己 `throw redirect()` 的回應不經過 `resolve` 之後的程式，要標頭就直接 `return new Response(null, { status: 303, headers: { location } })`。`vite dev` 不經自訂伺服器，靠 `handle` 這段擋。

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
	for (const [name, value] of securityHeaders(https)) {
		// 回應已有自己的 CSP（例如上傳檔案的 sandbox）時加成第二條政策，兩條都生效；不要蓋掉它
		if (name === 'content-security-policy' && response.headers.has(name)) response.headers.append(name, value);
		else response.headers.set(name, value);
	}
	return response;
};
```

`src/app.d.ts` 的 `App.Locals` 加上 `clientIp: string; https: boolean`。SvelteKit 2 的寫法差在兩處：`import type { Handle } from '@sveltejs/kit'`，以及用 `$lib/server/...` 匯入。

## FastAPI（Python）

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
import logging

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .client_ip import client_ip, ip_list, via_https
from .geoip import CountryGate  # 第 3 層；不做第 3 層就刪掉這行
from .security_headers import security_headers  # 見 session-and-headers.md

logger = logging.getLogger(__name__)

TRUSTED_PROXIES = ip_list("192.0.2.10")
ALLOWED_PEERS = ip_list("127.0.0.1, ::1, 192.0.2.10")
# 第 3 層；例外清單是本機與你自己的內網。不做第 3 層（代理已擋國家）就改成 gate = None
gate = CountryGate("/var/lib/geoip/GeoLite2-Country.mmdb", {"TW"}, ip_list("127.0.0.0/8, ::1, 198.51.100.0/24"))


def install_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        peer = request.client.host if request.client else ""
        https = via_https(peer, request.headers.get("x-forwarded-proto"), TRUSTED_PROXIES)
        ip = client_ip(peer, request.headers.get("x-forwarded-for"), TRUSTED_PROXIES)
        request.state.client_ip, request.state.https = ip, https
        if not ALLOWED_PEERS(peer) or (gate is not None and not gate.allows(ip)):
            response = PlainTextResponse("Forbidden", status_code=403)
        else:
            try:
                response = await call_next(request)
            except Exception:  # 讓 500 也帶標頭；Starlette 自己的 500 頁在這層外面產生
                logger.exception("unhandled_error")
                response = PlainTextResponse("Internal Server Error", status_code=500)
        for name, value in security_headers(https):
            if name == "Content-Security-Policy" and name in response.headers:
                response.headers.append(name, value)  # 保留回應自己的 CSP（例如 sandbox），兩條都生效
            else:
                response.headers.setdefault(name, value)
        return response
```
