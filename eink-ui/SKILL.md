---
name: eink-ui
description: Use when building, restyling, or reviewing a UI that must stay readable on e-ink / e-paper screens, including e-ink monitors, or when an interface shows washed-out colors or indistinguishable states on such a device.
---

# 電子紙介面規範

同一個畫面要在電子紙和一般 LCD 上都好用。電子紙多半只有灰階，所以以它為基準設計，顏色只是給 LCD 的輔助。

## 規則

1. **底色與文字**：淺色主題用 `#fff` 底、`#000` 字；深色主題用 `#000` 底、`#fff` 字。次要、提示、停用文字都用同一個文字色，層級靠字級、粗細、間距表達。
2. **突出重點**：用反白（底色和文字色互換）或加粗的文字色邊框。
3. **顏色**：可以用來幫 LCD 使用者區分，但每個彩色物件對底色的對比至少 7:1。小字一律用文字色，顏色只用在大字、粗邊框和圖示。顏色表達的區別，一律同時用形狀、圖示或文字表達，形狀是主要依據。
4. **線條與填色**：只用實色，不用灰色、漸層、陰影、半透明。

## 常見狀況

- 停用狀態：用虛線邊框加文字說明，不要淡化成灰色。
- 輸入框裡的提示文字不用灰色：改放到框外，或留在框內但用文字色斜體，和使用者輸入的內容區分。
- 內容本身的照片和圖表可保留灰階，只有介面元件受上述規則限制。

## 驗收

全部通過才算完成：

- 把截圖轉成灰階，所有狀態和分類的區別仍看得出來。
- 搜尋樣式碼，介面元件沒有 `box-shadow`、`gradient`、`opacity`，也沒有灰色的文字或邊框。
- 每個彩色物件對底色的對比都達 7:1，小字都是文字色。
