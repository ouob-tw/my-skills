---
name: structured-logging
description: Use when setting up logging for a new Python/FastAPI project, adding structured logging to an existing project, creating a logging module, or configuring JSON log output. Triggers include new projects needing observability, questions about log format standards, request tracing with request_id, or adding log context propagation.
---

# Structured Logging Standard

## Overview

Stdlib-only structured JSON logging for Python services. Each log line is a self-contained JSON object with fixed fields, contextvar-based request tracing, and a single `setup_logging()` entry point.

## When to Use

- Setting up logging for a new Python/FastAPI service
- Adding request_id tracing across async handlers
- Replacing unstructured `print()` or basic `logging.info()` with queryable JSON
- Standardizing log format across multiple services

## Quick Reference

### Fixed Fields

| Field | Source | Notes |
|-------|--------|-------|
| `ts` | UTC ISO 8601, ms precision | `2026-05-24T08:30:12.345+00:00` |
| `level` | INFO / WARNING / ERROR / DEBUG | |
| `logger` | `__name__` | |
| `layer` | `setup_logging(layer=...)` | Multi-service: distinguish origin. Single-service: use default `"app"` |
| `message` | `logger.info("event_name")` | Event identifier |

Protection: context or extra with same key name will NOT overwrite fixed fields.

### Context API

| Function | Purpose |
|----------|---------|
| `set_context(**kwargs)` | Merge non-None values, return token |
| `get_context()` | Return context copy |
| `clear_context(token)` | Reset via token, or pass None to clear all |

### Settings

```python
class Settings(BaseSettings):
    log_level: str = "INFO"
    log_dir: str = ""  # empty = stdout only
```

### Initialization

```python
from myproject.logging import setup_logging

setup_logging(
    layer="my-service",
    level=settings.log_level,
    log_dir=settings.log_dir or None,  # None = stdout only; path = stdout + daily rotation
)
```

## Implementation

### Core Module (logging.py)

```python
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "app_logging_context", default={}
)

_RESERVED_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}
_FIXED_FIELDS = frozenset({"ts", "level", "logger", "layer", "message"})
_STRUCTURED_HANDLER_ATTR = "_structured"


class JsonFormatter(logging.Formatter):
    def __init__(self, layer: str) -> None:
        super().__init__()
        self.layer = layer

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "layer": self.layer,
            "message": record.getMessage(),
        }
        data.update({k: v for k, v in get_context().items() if k not in _FIXED_FIELDS})
        data.update(_record_extras(record))
        if record.exc_info:
            data.setdefault("exc_type", record.exc_info[0].__name__)
            data.setdefault("exc_message", str(record.exc_info[1]))
            data.setdefault("traceback", self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def set_context(**kwargs: Any) -> contextvars.Token:
    current = get_context()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    return _context.set(current)


def get_context() -> dict[str, Any]:
    return dict(_context.get())


def clear_context(token: contextvars.Token | None = None) -> None:
    if token is not None:
        _context.reset(token)
        return
    _context.set({})


def setup_logging(layer: str = "app", level: str = "INFO", log_dir: str | None = None) -> None:
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    root_logger = logging.getLogger()
    _remove_structured_handlers(root_logger)
    for handler in _structured_handlers(layer, log_dir):
        root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        k: v for k, v in record.__dict__.items()
        if k not in _RESERVED_RECORD_KEYS and k not in _FIXED_FIELDS and not k.startswith("_")
    }


def _json_default(value: Any) -> str:
    if isinstance(value, bytes | bytearray):
        return f"<bytes:{len(value)}>"
    return str(value)


def _mark_structured(handler: logging.Handler, formatter: logging.Formatter) -> logging.Handler:
    handler.setFormatter(formatter)
    setattr(handler, _STRUCTURED_HANDLER_ATTR, True)
    return handler


def _structured_handlers(layer: str, log_dir: str | None) -> list[logging.Handler]:
    formatter = JsonFormatter(layer=layer)
    handlers: list[logging.Handler] = [_mark_structured(logging.StreamHandler(sys.stdout), formatter)]
    if log_dir is None:
        return handlers
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        log_path / f"{layer}.log", when="midnight", backupCount=180, encoding="utf-8",
    )
    handlers.append(_mark_structured(file_handler, formatter))
    return handlers


def _remove_structured_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _STRUCTURED_HANDLER_ATTR, False):
            logger.removeHandler(handler)
            handler.close()
```

### HTTP Middleware

```python
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .logging import clear_context, set_context

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = set_context(request_id=request_id)
        start = time.monotonic()
        status_code = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            extra = {
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_host": request.client.host if request.client else None,
            }
            if status_code is not None:
                logger.info("http_request", extra=extra)
            else:
                logger.error("http_request_failed", extra=extra, exc_info=True)
            clear_context(token)
```

## Optional Extensions

| Feature | When to add | Implementation |
|---------|-------------|----------------|
| **StageTimer** | Need latency tracking for specific code blocks | Context manager logging `stage_complete` / `stage_failed` with `duration_ms` |
| **GPU Stats** | CUDA/ML inference projects | Helper returning `mem_used_mb`, `mem_reserved_mb`, `mem_total_mb` |
| **run_in_executor_with_context** | async + blocking thread pool needing context propagation | `contextvars.copy_context().run(func, *args)` inside executor |

### StageTimer (if needed)

```python
class StageTimer:
    def __init__(self, stage_name: str, logger: logging.Logger | None = None) -> None:
        self.stage_name = stage_name
        self.logger = logger or logging.getLogger(__name__)
        self.duration_ms: int | None = None
        self._started_at: float = 0.0

    def __enter__(self) -> StageTimer:
        self._started_at = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.duration_ms = int((time.perf_counter() - self._started_at) * 1000)
        extra: dict[str, Any] = {"stage": self.stage_name, "duration_ms": self.duration_ms}
        if exc_type is None:
            self.logger.info("stage_complete", extra=extra)
            return False
        extra.update({"error": exc_type.__name__, "error_message": str(exc)})
        self.logger.error("stage_failed", extra=extra, exc_info=(exc_type, exc, tb))
        return False
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Calling `setup_logging()` multiple times | It's idempotent (removes old handlers first), but call once at entry point |
| Forgetting `clear_context()` in finally | Leaks context to unrelated requests |
| Passing `bytes` in extra fields | `_json_default` handles it, but prefer logging length/metadata instead |
| Using `print()` instead of `logger` | Won't go through JsonFormatter — use `logging.getLogger(__name__)` |
| Setting context in middleware but not clearing on exception | Always use `try/finally` with `clear_context(token)` |
