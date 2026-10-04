---
name: mermaid-flowchart-style
description: Use when styling Mermaid flowchart diagrams for GitHub, Obsidian, or MkDocs
---

# Mermaid Flowchart Style

## 標準 init 模板

三個平台（GitHub / Obsidian / MkDocs）都支援 `%%{init}%%`：

```
%%{init: {"flowchart": {"padding": 0}}}%%
flowchart TB
  ...
```

## 節點內距

`flowchart.padding`：文字到節點邊框的距離，預設 **15**，跨平台有效。

| 值  | 效果                         |
| --- | ---------------------------- |
| 15  | 預設，寬鬆                   |
| 6   | 偏緊湊                       |
| 0   | 最小，部分渲染器可能略微截字 |

> `nodePadding` 作為 themeVariable **無效**，不會被 Mermaid 處理。

## CSS Override（Obsidian / MkDocs，GitHub 無效）

在 md 檔案開頭加 `<style>` 區塊：

```html
<style>
  .nodeLabel {
    padding: 0 !important;
  } /* 節點文字內距 */
  .edgeLabel {
    padding: 0 !important;
  } /* 箭頭標籤內距 */
</style>
```

## 字體大小（已知限制，選用）

`themeVariables.fontSize` 在 flowchart 中**只影響視覺渲染，不影響節點框的計算尺寸**，字體放大後文字會溢出邊框。這是 Mermaid 已知的 open bug（[#2896](https://github.com/mermaid-js/mermaid/issues/2896)、[#2139](https://github.com/mermaid-js/mermaid/issues/2139)）。

如仍要調整，選一種方式：

**A. 全平台（接受溢出風險）**

```
%%{init: {"themeVariables": {"fontSize": "18px"}}}%%
```

**B. Obsidian / MkDocs 限定（搭配 `<style>` 區塊）**

```html
<style>
  .nodeLabel {
    font-size: 18px;
  }
</style>
```

> `htmlLabels: false` 改為 SVG text 模式，`<br/>` 換行仍有效，但無法解決字體與框寬不同步的問題。
