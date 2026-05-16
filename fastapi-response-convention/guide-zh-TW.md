# FastAPI 回應格式慣例 — 中文解說

> 這份文件是 SKILL.md 的中文解說版，幫助你理解每條規則背後的原因。
> AI 讀的是 SKILL.md（英文），這份是給人讀的。

---

## 這個 Skill 在解決什麼問題？

當 AI 幫你寫 FastAPI 端點時，它可能每次用不同的回應格式：有時成功回 `{"data": ...}`，有時直接回資料；有時錯誤用字串，有時用陣列。這個 Skill 統一了規則，讓 AI 每次都用一致的格式。

---

## 核心觀念：不是所有東西都要你定義

FastAPI 框架本身已經幫你處理了大部分格式：

```
你寫 response_model=MyModel  →  FastAPI 自動把回應轉成 JSON + 產生 API 文件
用戶送錯資料                  →  Pydantic 自動回 422 + 標準錯誤格式
```

**你只需要管框架管不到的兩個地方：**

1. 業務邏輯驗證失敗（例如「G2P 不認識這個字」）— 框架不知道這是錯的
2. 伺服器故障（例如「Worker 掛了」）— 框架沒有預設的 5xx 格式

---

## 五種 HTTP 狀態碼，三種處理方式

### 處理方式一：框架自動（你不用動）

| 狀態碼 | 什麼時候發生 | 回應長什麼樣 |
|--------|-------------|-------------|
| **200** 成功 | 正常回應 | 你的 `response_model` 定義的結構 |
| **422** Pydantic 驗證 | 用戶送的資料格式不對（缺欄位、型別錯） | `{ "detail": [{ "type": "string_too_short", "loc": ["body", "gen_text"], "msg": "..." }] }` |

你要做的：在端點加 `response_model` 參數，其他 FastAPI 全包。

### 處理方式二：手動但對齊框架格式

| 狀態碼 | 什麼時候發生 | 回應長什麼樣 |
|--------|-------------|-------------|
| **422** 業務驗證 | 資料格式對，但內容有問題（G2P 失敗、文字太長） | `{ "detail": [{ "type": "value_error", "loc": ["body", "gen_text"], "msg": "包含無法辨識的詞彙：xyz" }] }` |

**為什麼要跟 Pydantic 格式一樣？**

前端只需要一種解析 422 的邏輯：

```javascript
// 前端不用管是 Pydantic 擋的還是業務邏輯擋的
if (response.status === 422) {
    showError(response.data.detail[0].msg)  // 永遠這樣讀
}
```

如果業務 422 用不同格式（比如 `{ "error": "...", "message": "..." }`），前端就要加一堆 if-else 判斷是哪種 422。

**怎麼寫：** 用 helper function 集中管理，不要每次手動拼 dict：

```python
# 定義一次
def _text_error(msg: str, field: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=[{
            "type": "value_error",
            "loc": ["body", field],
            "msg": msg,
            "input": None,
        }],
    )

# 使用時
raise _text_error("包含無法辨識的詞彙：xyz", "gen_text")
raise _text_error("文字過長", "gen_text")
```

### 處理方式三：自訂格式

| 狀態碼 | 什麼時候發生 | 回應長什麼樣 |
|--------|-------------|-------------|
| **401** 認證失敗 | Token 無效或缺少 | `{ "detail": "Invalid or missing authentication token" }` |
| **503** 服務不可用 | Worker 掛了、Modal 啟動中 | `{ "error": "worker_error", "message": "本地 Worker 回應錯誤，請稍後重試", "request_id": "..." }` |

**401 為什麼用字串不用陣列？**
認證失敗就是認證失敗，不需要告訴用戶「哪個欄位錯了」。前端看到 401 就跳轉登入頁面，不需要 parse 細節。這也是 OAuth2 / JWT 的業界慣例。

**503 為什麼用不同結構？**
503 需要攜帶額外資訊（`fallback_status`、`estimated_ready_seconds`），讓前端決定要不要顯示「正在啟動，請等 30 秒」。這些資訊塞進 `detail` 陣列格式不自然。

**怎麼寫：** 定義一個共用的 ErrorResponse model：

```python
class ErrorResponse(BaseModel):
    error: str                              # 機器讀的代碼：worker_error, modal_error
    message: str                            # 人讀的訊息：「請稍後重試」
    request_id: str | None = None           # 追蹤用
    # 可按專案需求擴充欄位

# 使用時
return JSONResponse(
    status_code=503,
    content=ErrorResponse(
        error="worker_error",
        message="本地 Worker 回應錯誤，請稍後重試",
        request_id=request_id,
    ).model_dump(),
)
```

---

## 前端的判斷流程

整理成一張圖，前端只需要：

```
收到回應
  │
  ├─ status 200~299 → 直接用 response body
  │
  ├─ status 401     → 跳轉登入（不用 parse body）
  │
  ├─ status 422     → 顯示 response.detail[0].msg
  │                    （不管是 Pydantic 還是業務邏輯產生的）
  │
  └─ status 503     → 讀 response.error 決定策略
                       顯示 response.message 給用戶
                       若 fallback_status === "warming" → 顯示倒數
```

**這就是為什麼不同狀態碼用不同結構是合理的** — HTTP status code 本身就是 discriminator，前端用 status code 分流，每條路只有一種 JSON 結構要解析。

---

## response_model 是什麼？為什麼一定要加？

`response_model` 是 FastAPI 端點的參數，告訴框架「這個端點的成功回應長什麼樣」：

```python
@router.post("/sync", response_model=TTSSyncResponse)  # ← 加這個
async def sync_tts(...):
    return TTSSyncResponse(audio_base64=..., sample_rate=...)
```

加了之後 FastAPI 會：
1. **自動驗證** — 如果你回傳的資料不符合 model，會報錯（開發時就抓到）
2. **自動過濾** — 多餘的欄位不會洩漏給用戶（安全性）
3. **自動文件** — OpenAPI / Swagger 頁面自動顯示回應結構（前端可以直接看）

不加的話，這三個好處都沒有，AI 也容易每次回傳不同結構的 dict。

---

## 固定欄位速查：資料在哪？錯誤訊息在哪？追蹤 ID 在哪？

不管哪個端點，前端永遠去同一個位置找資料：

### 成功回應（2xx）

| 你要的東西 | 在哪裡 |
|---|---|
| 資料 | **response body 本身就是資料**（沒有 `data` 包裝層） |
| 請求追蹤 ID | `response.request_id` |

```json
{
  "audio_base64": "...",
  "sample_rate": 24000,
  "request_id": "6a7b4505-..."
}
```

### 錯誤回應 — 三個固定入口

| | 422（輸入問題） | 5xx（服務問題） | 401（認證問題） |
|---|---|---|---|
| **錯誤訊息（給用戶看）** | `.detail[0].msg` | `.message` | `.detail`（字串） |
| **錯誤代碼（程式判斷用）** | `.detail[0].type` | `.error` | 不需要，看到 401 就跳登入 |
| **哪個欄位出錯** | `.detail[0].loc` | 不適用 | 不適用 |
| **請求追蹤 ID** | 無 | `.request_id` | 無 |

每種狀態碼的 JSON 結構：

```json
// 422 — 輸入有問題
{
  "detail": [{
    "type": "value_error",         // ← 錯誤代碼
    "loc": ["body", "gen_text"],   // ← 哪個欄位
    "msg": "包含無法辨識的詞彙：xyz", // ← 錯誤訊息
    "input": null
  }]
}

// 503 — 服務有問題
{
  "error": "worker_error",         // ← 錯誤代碼
  "message": "本地 Worker 回應錯誤", // ← 錯誤訊息
  "request_id": "6a7b4505-..."     // ← 追蹤 ID
}

// 401 — 認證失敗
{
  "detail": "Invalid or missing authentication token"  // ← 就這一個字串
}
```

### 前端萬用解析邏輯

這段邏輯適用於所有端點，不需要按端點修改：

```typescript
function handleResponse(status: number, body: any) {
  if (status >= 200 && status < 300) {
    return body                          // body 本身就是資料
  }
  if (status === 401) {
    redirectToLogin()
    return
  }
  if (status === 422) {
    const msg = body.detail?.[0]?.msg    // 永遠在這裡
    const field = body.detail?.[0]?.loc?.at(-1)
    showFieldError(field, msg)
    return
  }
  if (status >= 500) {
    const code = body.error              // "worker_error" 等
    const msg = body.message             // 中文錯誤訊息
    const rid = body.request_id          // 回報問題時附上
    if (body.fallback_status === 'warming') {
      showRetryCountdown(body.estimated_ready_seconds)
    } else {
      showError(msg)
    }
    return
  }
}
```

---

## 常見 AI 犯的錯（這個 Skill 要擋的）

| AI 常做的事 | 為什麼不好 | 正確做法 |
|------------|-----------|---------|
| 422 的 detail 寫成字串 | 前端要多一種解析路徑 | 永遠用陣列 `[{type, loc, msg}]` |
| 每個 router 定義自己的 ErrorResponse | 格式漸漸分歧 | 共用一個，放在 `schemas/` |
| 成功回應用 `JSONResponse({...})` | 失去自動驗證和 API 文件 | 用 `response_model` |
| 把所有回應包在 `{"data":..., "error":...}` | 跟 FastAPI 預設格式衝突 | 不要用 envelope |
| 為單一端點發明新的錯誤格式 | 前端要新增解析邏輯 | 沿用專案現有的 error helper |

---

## 一句話總結

**讓框架管它能管的（成功回應 + Pydantic 422），你只統一管兩個缺口（業務 422 對齊 Pydantic 格式、5xx 用共用 ErrorResponse）。**
