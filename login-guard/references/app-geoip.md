# 第 3 層：程式內 GeoIP（備案）

沒有能設定的代理，或想多一層時才做。規則與理由：

- 判斷用第 2 層算出的真實 IP（[client-ip.md](client-ip.md)）。
- **例外清單先比**：本機與你自己的內網段（從設定讀），不查資料庫。
- **查不到國家就擋**（`AddressNotFoundError`、不是 IP）。
- **沒有資料庫就只放例外清單**。資料庫壞掉時「全部放行」等於限制失效而沒人發現；真要選放行，寫成明確的設定與紀錄，不要當預設。
- **資料庫被替換後重新開啟**：更新程式原子替換檔案後，程式要重開 reader（例如每小時比一次檔案修改時間，或收到訊號時）。重開失敗就保留舊的 reader。沿用 [proxy-geoip.md](proxy-geoip.md) 的更新程式時：刪掉寫 `country.conf` 的那個 `if` 區塊；把 `if ! nginx -t || ! nginx -s reload; then` 整行換成 `if ! systemctl kill -s HUP <服務>; then`（或其他通知程式重新載入的指令，前面的 `!` 要留著：通知失敗才進還原），區塊裡的還原照舊，`FAILED` 訊息裡的 nginx 改成你的服務名稱；區塊裡另一行 `nginx -t && nginx -s reload || true` 也刪掉。
- 被擋時寫一行紀錄，帶真實 IP 與查到的國家碼。

## Node：`@maxmind/geoip2-node`

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

## Python：`geoip2`

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
