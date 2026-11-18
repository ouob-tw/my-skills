# 第 1 層：反向代理擋國家

規則與理由：

- **用實際 TCP 來源判斷國家**，nginx 是 `$realip_remote_addr`，不是 `$remote_addr`。很多代理的全域設定（例如 Nginx Proxy Manager 預設）會相信內網或 Docker 網段送來的 `X-Real-IP` 並改寫 `$remote_addr`，內網的人就能自稱任何 IP。在這個站的 `server` 裡寫 `set_real_ip_from unix:;`，取代繼承來的信任清單。
- **在 `server` 層級擋**（`if (...) { return 403; }`），不要只寫在 `location /`。管理介面自己加的 location（例如 NPM 的「Cache Assets」會加一個比對 `.js`、`.css`、`.png` 的 regex location）會繞過 `location /`，國外照樣拿得到靜態檔，甚至打到 `/api/x.js` 這種路徑。
- **轉給程式的 `X-Forwarded-For` 覆寫成實際來源**（`proxy_set_header X-Forwarded-For $realip_remote_addr;`），不要用 `$proxy_add_x_forwarded_for` 把訪客送來的值接在後面。程式就只會看到一個、而且是真的位址。
- **沒有資料庫時只有內網進得來**：國家變數預設空字串，資料庫驗證過才由更新程式寫出啟用查詢的 include。`geoip2` 指令遇到不存在的檔案會讓 `nginx -t` 失敗，代理重啟時整台機器上的網站都起不來；所以絕不能只刪 `.mmdb` 而留著引用它的 include，要先刪 include 或一起刪。
- **內網例外只寫你自己的網段**，寫死整個 10/8、172.16/12、192.168/16 會把同網段的容器、VPN 也放進來。
- 代理上還有別的網站時，變數名稱加前綴，只有這個站引用，其他站不受影響。

## nginx（含 ngx_http_geoip2_module）

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
    198.51.100.0/24  1;   # 換成你自己的內網
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

## Nginx Proxy Manager

- 先確認映像檔有模組：`ls /usr/lib/nginx/modules/ | grep geoip2`。
- `load_module` 放 `data/nginx/custom/root_top.conf`；上面 http 層級的 `map`、`geo`、`include` 放 `data/nginx/custom/http_top.conf`。這兩個檔 NPM 重建設定時會保留。
- `set_real_ip_from`、`if` 與 `location /` 放在該站的 Advanced 欄位；Advanced 裡寫了 `location /` 時，NPM 不再產生自己的，所以要把它原本的 `proxy_set_header` 也搬進來。
- 改完用 NPM 介面再存一次該站，確認規則還在。

## 資料庫來源與每日更新

- **預設用 MaxMind 官方 GeoLite2 Country**：要免費帳號與授權碼，用官方 `geoipupdate` 下載（本身會原子替換），跑完後重新載入 nginx 或程式。
- 不想註冊帳號時，才用第三方轉載的 GeoLite2 `.mmdb`（例如 GitHub releases 上的鏡像）配下面的更新程式。它不是官方，對方停更或下載失敗時會一直用舊資料，國家判斷慢慢不準，所以失敗一定要留紀錄。
- 每天一次，用 systemd timer 或 cron；排程寫明時區（UTC）並加隨機延遲，避免整點一起下載。

更新程式（下載 → 驗證 → 原子替換 → 重新載入；任何一步失敗都還原舊檔、exit 1、錯誤寫到 stderr 進 journal）：

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
[ -f "$DB" ] && cp -p "$DB" "$DB.prev"
mv "$tmp" "$DB"
new_conf=0
# 啟用查詢的 include 只在有了有效資料庫之後才寫。
if [ ! -f "$DIR/country.conf" ]; then
    cat > "$DIR/country.conf" <<CONF
geoip2 $DB {
    \$login_country source=\$realip_remote_addr country iso_code;
}
CONF
    new_conf=1
fi
# set -e 不管 if 條件與 && 左邊的失敗，所以這裡明確處理：nginx 不接受就還原，維持原本能運作的狀態。
if ! nginx -t || ! nginx -s reload; then
    if [ -f "$DB.prev" ]; then
        mv "$DB.prev" "$DB"
    else
        rm -f "$DIR/country.conf" "$DB"   # 先前沒有資料庫：回到「只放內網」
    fi
    [ "$new_conf" = 1 ] && rm -f "$DIR/country.conf"
    nginx -t && nginx -s reload || true
    echo "FAILED: nginx rejected the new database; previous state restored" >&2
    exit 1
fi
rm -f "$DB.prev"
echo "updated"
```

`mmdblookup` 來自 libmaxminddb（Debian `mmdb-bin`、Alpine `libmaxminddb`）；查不到 `CHECK_IP` 時它的結束碼不是 0，所以壞檔與空資料庫都會被擋下。
