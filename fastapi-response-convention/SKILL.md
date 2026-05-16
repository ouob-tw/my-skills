---
name: fastapi-response-convention
description: Use when creating or modifying FastAPI endpoints, adding error handling, defining response schemas, or reviewing API response consistency. Triggers include new routers, HTTPException usage, JSONResponse construction, Pydantic response models, or any question about API error/success format in a FastAPI project.
---

# FastAPI Response Convention

## Overview

FastAPI projects follow HTTP-native response conventions. Success responses use `response_model` for automatic serialization and OpenAPI docs. Error responses split by HTTP status code category — each category has ONE fixed format. Do not introduce response envelopes (`{ "data": ..., "error": ... }`).

## Core Principle

**Framework handles success; you define the gaps.** FastAPI auto-generates OpenAPI specs from `response_model` and auto-formats Pydantic validation errors. You only need to define formats for two gaps: business-logic 422s and 5xx errors.

## Quick Reference

| Status | Format | Who handles | Frontend action |
|--------|--------|-------------|-----------------|
| 2xx | Direct payload via `response_model` | FastAPI automatic | Use data |
| 401/403 | `{ "detail": "string" }` | `HTTPException(detail="msg")` | Redirect to login |
| 422 (Pydantic) | `{ "detail": [{ type, loc, msg }] }` | FastAPI automatic | Show `detail[0].msg` |
| 422 (business) | `{ "detail": [{ type, loc, msg, input }] }` | Manual — match Pydantic format | Show `detail[0].msg` |
| 5xx | `{ "error": "code", "message": "human text" }` | `JSONResponse` + project ErrorResponse model | Read `error`, show `message` |

## Rules

### Success responses
1. Every endpoint MUST have a `response_model` parameter
2. Response models live in `schemas/` directory — check for existing ones before creating new
3. Return Pydantic model instances or dicts that match the model

### 422 business validation errors
4. Use `raise HTTPException(status_code=422, detail=[...])` — detail MUST be an **array**, not a string
5. Each item: `{"type": "value_error", "loc": ["body", "<field>"], "msg": "<message>", "input": None}`
6. Centralize in helper functions (one per router or shared), do not inline dict construction at call sites
7. Match Pydantic's `detail` array format so frontend has ONE parsing path for all 422s

### 5xx server errors
8. Use `JSONResponse(status_code=5xx, content=ErrorModel(...).model_dump())`
9. Define ONE `ErrorResponse` Pydantic model per project with at minimum `error` (machine code) and `message` (human text)
10. Do not duplicate ErrorResponse — if one exists, reuse it
11. Never expose stack traces or internal error messages to clients

### Do NOT
- Wrap success responses in `{ "data": ..., "error": ... }` envelopes
- Override FastAPI's default validation exception handler (unless the project already does)
- Use `JSONResponse` for success responses when `response_model` works
- Create per-endpoint error formats — use the project's shared ErrorResponse

## Applying to an Existing Project

Before writing new endpoints, audit:

```
1. grep -rn "response_model" routers/     → which endpoints already declare it?
2. grep -rn "HTTPException\|JSONResponse" routers/ → how are errors raised now?
3. ls schemas/                             → what response models exist?
4. Look for existing error helpers         → reuse them, don't create new ones
```

Follow whatever patterns the project already established. If the project has `_text_error()` helpers, use those. If it has an `ErrorResponse` model, use that. Consistency with the existing codebase beats theoretical purity.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `HTTPException(detail="string")` for 422 | Use `detail=[{type, loc, msg, input}]` array |
| New `ErrorResponse` class per router | Reuse the project's existing one |
| `JSONResponse({...})` for success | Use `response_model` + return model instance |
| Inventing new error format for one endpoint | Follow the project's existing error pattern |
| `detail` as string for business 422 | Array format — must match Pydantic's auto-422 |
