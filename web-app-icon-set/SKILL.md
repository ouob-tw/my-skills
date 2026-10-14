---
name: web-app-icon-set
description: Use when turning a square artwork or logo into a web app's icon set (favicon, apple-touch-icon, web manifest / PWA / add-to-home-screen icons), or when an installed icon looks wrong — sharp square corners in the browser tab, black corners on iPhone, cropped or boxed-in icons on Android.
compatibility: Requires uv (the script declares Pillow inline). Previewing needs a headless browser such as Playwright.
---

# Web App 圖示組

把一張方形原圖切成瀏覽器分頁、iPhone 主畫面、Android 主畫面都正確的圖示組。

核心規則：**誰負責裁形狀，就決定檔案要不要自己做圓角。**

| 檔案 | 誰顯示 | 系統會自己裁形狀嗎 | 做法 |
| --- | --- | --- | --- |
| `favicon.ico`、`favicon-16/32.png` | 瀏覽器分頁、書籤 | 不會，照原樣顯示 | 自己做圓角，角外透明 |
| `icon-192.png`、`icon-512.png`（manifest `purpose: "any"`） | 部分 Android 桌面、安裝畫面、桌面版 PWA | 不一定 | 自己做圓角，角外透明 |
| `icon-512-maskable.png`（manifest `purpose: "maskable"`） | Android 桌面 | 會，裁成圓、圓角方形等桌面的形狀 | 方形滿版、不透明 |
| `apple-touch-icon.png`（180） | iPhone/iPad 主畫面 | 會，自動套圓角 | 方形滿版、不透明 |

## 流程

1. 確認原圖是方形、至少 512 px、背景是滿版單色或滿版畫面（不是透明底）。
2. 檢查構圖能否套圓形遮罩：Android 只保證中間直徑 80% 的圓不被裁到。頭、臉等辨識重點要在這個圓內；身體邊緣被切掉沒關係。重點超出時，請畫圖的人出一張往中間收的版本，只給 maskable 用。
3. 切圖：

   ```bash
   uv run scripts/make_icons.py <原圖.png> <專案靜態檔目錄>
   ```

   預設圓角半徑是邊長的 22.5%，接近 iOS 的圓角；使用者想要不同弧度時用 `--radius` 調整。
4. 寫 manifest，`any` 和 `maskable` 一定要指向**不同檔案**：

   ```json
   {
     "name": "<App 名稱>",
     "short_name": "<短名>",
     "start_url": "/",
     "display": "standalone",
     "background_color": "<app 底色>",
     "theme_color": "<app 底色>",
     "icons": [
       { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
       { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
       { "src": "/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
     ]
   }
   ```

5. 在頁面 `<head>` 加連結：

   ```html
   <link rel="icon" href="/favicon.ico" sizes="any" />
   <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
   <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
   <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
   <link rel="manifest" href="/manifest.webmanifest" />
   <meta name="theme-color" content="<app 底色>" />
   ```

6. 驗收（全部通過才算完成）：
   - 用無頭瀏覽器做一張預覽圖：淺色與深色分頁上的 16/32 px、圓角方形的 180 px、`border-radius: 50%` 的 maskable，實際看過再交付。
   - 檢查檔案：`any` 與 favicon 的左上角像素 alpha 為 0；`apple-touch-icon` 與 maskable 為 RGB（不透明）。
   - 部署後對每個檔案和 manifest 發請求，確認回應 200，且 manifest 是合法 JSON。

## Gotchas

- 把同一張圖同時標 `any` 和 `maskable`：做了圓角，Android 會在圓角外多一圈底色；沒做圓角，瀏覽器分頁又是尖角方塊。一定要分兩張。
- `apple-touch-icon` 留透明角，iPhone 會把透明處填成黑色。
- 只有 `any`、沒有 `maskable` 時，Android 常把圖縮小放進白色圓形底，看起來像被框住。
- 縮圖時直接用圓角遮罩會出鋸齒，要先以 4 倍大小畫遮罩再縮小（腳本已處理）。
- 角色只佔畫面一角、頭很小的構圖，16 px 時會糊成一團。提供多張候選時，優先選頭部佔比大的那張當圖示。
- 瀏覽器和手機會暫存舊圖示：分頁要重新整理，已加到主畫面的捷徑要刪掉重加，才會換成新圖。
- SvelteKit adapter-node 等部分靜態伺服器回傳 `.ico` 時不帶 Content-Type，瀏覽器仍能顯示，也有 PNG 版可用，不必為此改伺服器。
