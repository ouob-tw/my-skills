---
name: three-tier-testing
description: Use when setting up test infrastructure, adding tests, reorganizing test directories, or reviewing test structure in Python (pytest) or TypeScript (Playwright/Vitest) projects. Triggers include creating test files, discussing test strategy, separating unit from integration tests, or when tests need external services like databases or Docker.
---

# 三層測試架構

依照外部依賴程度，將測試分為三層。每層獨立運行，一條指令執行。

| 層級     | 目錄                            | 金鑰 | 目的                                   |
| -------- | ------------------------------- | ---- | -------------------------------------- |
| 單元測試 | `tests/unit/`                   | 無   | 邏輯正確性 — 純程式碼，所有依賴皆 mock |
| 整合測試 | `tests/integration/`            | 假的 | 服務串接 — 真實 DB、真實查詢           |
| E2E 測試 | `tests/e2e/` 或 `frontend/e2e/` | 真的 | 完整使用者流程，含外部服務             |

## 整合測試環境：Host（預設） vs Docker

預設使用 **Host**：整合測試直接連本機的開發資料庫，設定最簡單，適合大多數專案。

若專案有多資料庫、訊息佇列、或已有 Docker Compose 開發環境，改用 **Docker**：整合測試透過 `docker-compose.test.yml` 啟動獨立容器。

```
本機已跑單一 DB？          → Host（預設）
開發流程已有 Docker Compose？ → Docker
多資料庫 / 訊息佇列？       → Docker
```

## 規則：裸跑 `pytest` = 只跑單元測試

不帶任何參數執行 `pytest` 時，只會執行單元測試。整合與 E2E 需要明確指定。這由 `pyproject.toml` 的 `testpaths` 控制。

## 設定（Python / pytest）

### 1. 目錄結構

```
tests/
  unit/
    __init__.py
    conftest.py          ← 單元測試共用 fixture（無 DB）
  integration/
    __init__.py
    conftest.py          ← DB engine、自動標記、環境載入
  e2e/                   ← 可選，或用 frontend/e2e/
    conftest.py
```

### 2. pyproject.toml

```toml
[tool.pytest.ini_options]
testpaths = ["tests/unit"]
markers = [
    "integration: requires services (DB, cache)",
    "e2e: requires full stack with real external keys",
]
```

### 3. 自動標記 conftest.py

每一層的 `conftest.py` 自動套用對應標記，測試檔案不需要手動加 `@pytest.mark.integration`：

```python
# tests/integration/conftest.py
import pytest

def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.integration)
```

`tests/e2e/conftest.py` 同理，改用 `pytest.mark.e2e`。

### 4. 整合測試環境

**Host（預設）：** `.env.test` 指向本機開發 DB。整合測試的 conftest 用 `load_dotenv(".env.test", override=True)` 以 session scope autouse fixture 載入。

**Docker：** 建立 `docker-compose.test.yml`，服務使用非預設 port（如 Postgres 用 5433）。整合測試的 conftest 以 session scope autouse fixture 啟動／關閉容器。

### 5. 執行指令

```bash
# 只跑單元測試（預設）
pytest

# 只跑整合測試
pytest tests/integration -m integration

# 全部 Python 測試
pytest tests/unit tests/integration

# E2E（前端）
bunx playwright test

# E2E（Python）
pytest tests/e2e -m e2e
```

## 設定（TypeScript / 前端）

| 層級     | 工具       | 目錄               |
| -------- | ---------- | ------------------ |
| 單元測試 | Vitest     | `src/**/*.test.ts` |
| E2E      | Playwright | `e2e/*.spec.ts`    |

## 測試歸屬判斷

### 單元測試（`tests/unit/`）

- 函式邏輯搭配 mock 依賴
- 資料轉換、驗證、解析
- 類別行為搭配假協作物件

**確認是單元測試的跡象：** 用到 `monkeypatch` / `MagicMock`、沒有 DB fixture、每個測試 < 0.1 秒。

### 整合測試（`tests/integration/`）

- 資料庫 migration（表結構、索引、約束）
- Repository / Manager 的 CRUD（真實 SQL）
- API endpoint 經由 test client 加真實 DB

**確認是整合測試的跡象：** 用到 `test_engine` / `db_session`、import `text()`、需要載入 `.env.test`。

### E2E 測試（`tests/e2e/` 或 `frontend/e2e/`）

- 瀏覽器驅動的使用者流程（Playwright）
- 完整 API 呼叫鏈搭配真實外部服務與真實 API 金鑰

## 從扁平 tests/ 遷移

- [ ] 建立 `tests/unit/` 和 `tests/integration/`，各放 `__init__.py`
- [ ] 逐一檢查測試檔：用到 DB fixture → `integration/`，純 mock → `unit/`
- [ ] 拆分 `conftest.py`：DB fixture → `integration/conftest.py`，其餘 → `unit/conftest.py`
- [ ] `pyproject.toml` 設定 `testpaths = ["tests/unit"]`
- [ ] 每層加上自動標記 `conftest.py`
- [ ] 執行驗證（見下方）

### 驗證迴圈

遷移後反覆執行以下檢查，直到兩者都正確：

```bash
# 必須只收集單元測試（無 DB fixture、無 integration 標記）
pytest --collect-only

# 必須只收集整合測試（全部標記為 integration）
pytest tests/integration -m integration --collect-only
```

若單元測試收集到整合測試，代表檔案放錯目錄或仍 import 了 DB fixture。若整合測試收集結果為空，代表自動標記 conftest 遺漏或缺少 `__init__.py`。

## 注意事項

- `testpaths = ["tests/unit"]` 是核心設定。若改成 `tests/` 或包含 `tests/integration`，裸跑 `pytest` 就會執行整合測試，破壞層級隔離。
- 每個測試子目錄都需要 `__init__.py`，缺少的話 pytest 會靜默跳過該目錄。
- 若測試 import 了真實 DB engine，即使放在 `tests/unit/` 也是整合測試。正確做法是搬移檔案，不是 mock import。
- **Docker 模式：** 使用非預設 host port（如 `5433:5432`），避免與開發 DB 衝突。
- **Host 模式：** 本機 DB 必須在測試前啟動。若測試出現連線錯誤，先檢查這點。可在整合測試 conftest 加連線檢查，提供清楚的錯誤訊息。
