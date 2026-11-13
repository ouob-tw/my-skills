---
name: xiaomi-phone-remote
description: Use when remote-controlling a Xiaomi, Redmi or POCO phone (MIUI / HyperOS) over adb, especially when installing an APK, or when adb install fails with INSTALL_FAILED_USER_RESTRICTED.
---

# 小米／Redmi／POCO 手機遠端操作

## 安裝 APK：10 秒內按「繼續安裝」

小米會在 `adb install` 把檔案傳完之後，由 `com.miui.securitycenter` 跳出「USB安裝提醒」。視窗寫著 App 名稱，下面有「繼續安裝」和倒數的「拒絕（N）」兩個按鈕。倒數大約 10 秒，歸零時當作拒絕，adb 回 `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`，雖然根本沒人按。

1. `adb install` 放背景跑。大檔要傳十幾秒，提醒在傳完後才跳出來，不是一開始就有。
2. 同時每 0.5 秒左右跑一次 `uiautomator dump`。`screencap` 常常截不到這個視窗，以 XML 為準。
3. XML 裡的 App 名稱對上時，在同一輪點「繼續安裝」，座標取它 `bounds` 的中心。「拒絕後下次安裝不再提醒」維持不勾，勾了以後就不再出現提醒，只會直接失敗。

同一個錯誤也可能是開發者選項的「透過 USB 安裝」沒開。這時提醒根本不會出現，XML 裡找不到它。這個開關只能由手機主人打開（常要求插 SIM、登入小米帳號），代理人不能代開。先 `adb push` 再 `pm install` 也會被同一個限制擋下，繞不過去。

## 打字與輸入法

用 Mobilerun Portal 之類的工具打字，會把系統預設輸入法換成它自己的鍵盤，而且結束後不會換回來。開始前先記下 `settings get secure default_input_method`，交還手機前改回原值。

## 解鎖

`dumpsys window | grep isKeyguardShowing` 剛解鎖時偶爾還會回 `true`，以截圖為準。小米鎖定畫面上滑的距離太長，會直接打開 App 抽屜。
