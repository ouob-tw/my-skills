---
name: structured-logging
description: "Use when adding or reviewing logging in a service (Python/FastAPI, Node/TypeScript, SvelteKit or similar) — JSON log lines, the fixed log fields, request_id tracing, logging exceptions and 5xx responses, or keeping passwords, tokens and user content out of logs."
---

# Structured Logging Standard

Every service writes logs the same way, whatever its language, so one query works across all of them. This file holds the rules; the code lives in one reference per language.

## Pick your language

- Python / FastAPI: read [references/python.md](references/python.md).
- Node / TypeScript (any HTTP framework; SvelteKit example included): read [references/typescript.md](references/typescript.md).
- Anything else: implement the rules below, using the closer of the two references as the template.

## Rules

### One JSON object per line

Each event is one compact JSON object on one line. Non-ASCII text stays as written (Python: `ensure_ascii=False`; `JSON.stringify` already does). Values that are not JSON (bytes, big integers, custom objects) become a short marker (`<bytes:42>`) or a string cut to a few hundred characters, never dumped whole.

### Fixed fields

| Field | Value |
|-------|-------|
| `ts` | Event time, UTC, ISO 8601 with milliseconds (`2026-05-24T08:30:12.345+00:00` or `…Z`) |
| `level` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `logger` | Module or component name (`__name__`, `app.http`) |
| `layer` | Service name, set once at start-up; `"app"` when there is only one service |
| `message` | Event name in snake_case (`http_error`, `stage_complete`), never a sentence or interpolated data |

Event details go in extra fields beside them (`method`, `path`, `status`, `duration_ms`). No extra field and no context value may overwrite a fixed field or `request_id`: the logger drops the colliding key, so a field named `message` is renamed by the caller (for example to `detail`).

### request_id

- Every request gets one id: the incoming `x-request-id` header when it is a short plain token (letters, digits, `.`, `:`, `_`, `-`, at most 128 characters), otherwise a new UUID.
- The id is held in request-scoped context (Python `contextvars`, Node `AsyncLocalStorage`) so every line logged while handling the request carries `request_id`, however deep the call. Context is cleared or scoped so it never leaks into the next request.
- Error hooks that a framework calls outside that scope keep the id on the request object and re-enter the context with it.

### Exceptions

An exception is logged once, where it is handled, with `exc_type` (class name), `exc_message` and `traceback` (full stack). An unhandled exception in a request also gets `method`, `path` and the `500` status it causes, on the same line or a separate `ERROR` line.

### What to log

- Every response with status 500 or above: one `ERROR` line with `method`, `path`, `status` and the failure reason the response carried.
- Expected refusals (4xx) are not errors; log them at `INFO` or not at all.
- A per-request access line (`INFO`, with `duration_ms`) is optional per project.

### Never log secrets or user content

Passwords, tokens, cookies, `Authorization` headers and user content (message bodies, form answers, uploaded files) never reach a log line. Log metadata about them instead (length, count, id).

Text a line copies from somewhere else (a response's reason, an exception message or stack, a library error) can still carry them, so it passes a **redactor** first:

1. Collect the request's secrets: the token from its cookie or header and the values of its content fields, each also trimmed, with line breaks normalised, JSON-escaped, and each line of four or more characters (shorter lines are too common to take out). Read the body from a copy: JSON whatever its declared content type, and URL-encoded or multipart forms.
2. Replace every occurrence with `[omitted]`, longest first.
3. Also replace what libraries quote back: input a JSON parser could not read, an argument a child process refused, and the query and fragment of every URL.
4. Cut the text to its length limit only after redacting: a secret split by the cut is no longer recognised.

Anything a client sends to be logged (browser error reports) is untrusted: log only what the server can validate (an error type from a fixed list, a canonical message for a recognised template, script locations that exist in the build, a known page path) and `[omitted]` for the rest.

### Where output goes

Write to stdout or stderr and let the platform collect it (systemd journal, container runtime). A daily rotating file is optional, for hosts without a collector; the Python reference has one.

## Gotchas

- Truncating before redacting leaks most of a token placed across the limit.
- Error messages from runtimes quote their input: Node's `Received '…'` for bad arguments and `JSON.parse`'s `"…" is not valid JSON` preview (cut short with `...` when long) repeat user text or file content verbatim.
- A framework can fail before the request middleware runs (route module loading): the error hook then has no request id and no response line unless it creates both itself.
- Exact-value redaction cannot recognise a reason that quotes only a few words of the user's text; keep user text out of error reasons at the source.
