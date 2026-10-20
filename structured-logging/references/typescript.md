# Node / TypeScript implementation

Dependency-free implementation of the rules in SKILL.md for Node 18+ or Bun: `AsyncLocalStorage` carries the request id, `logLine` builds the line, and one request wrapper logs 5xx responses and unhandled exceptions. Copy `log.ts` and `redact.ts` into the project, then wrap requests with the generic wrapper or the SvelteKit hooks below.

## log.ts

```ts
import { AsyncLocalStorage } from 'node:async_hooks';

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

/** The service name; set it once at start-up. */
let layer = 'app';
export const setLayer = (name: string) => void (layer = name);

const FIXED = new Set(['ts', 'level', 'logger', 'layer', 'message', 'request_id']);
const MAX_VALUE = 300;
const context = new AsyncLocalStorage<{ requestId: string }>();

/** Run `action` with this request id on every line it logs, however deep the call. */
export const withRequestId = <T>(requestId: string, action: () => T): T => context.run({ requestId }, action);

export function logLine(level: LogLevel, logger: string, message: string, extra: Record<string, unknown> = {}, now = new Date()): string {
	const record: Record<string, unknown> = { ts: now.toISOString(), level, logger, layer, message };
	const requestId = context.getStore()?.requestId;
	if (requestId) record.request_id = requestId;
	for (const [key, value] of Object.entries(extra)) {
		if (!FIXED.has(key) && value !== undefined) record[key] = value;
	}
	return JSON.stringify(record, safeValue);
}

/** JSON.stringify replacer for values that are not JSON: a marker or a short string, never the whole value. */
function safeValue(this: Record<string, unknown>, key: string, value: unknown): unknown {
	const raw = this[key];
	if (raw instanceof Uint8Array || raw instanceof ArrayBuffer) return `<bytes:${raw.byteLength}>`;
	if (typeof raw === 'bigint') return raw.toString();
	if (raw instanceof Error) return `${raw.name}: ${raw.message}`.slice(0, MAX_VALUE);
	return value;
}

export function log(level: LogLevel, logger: string, message: string, extra?: Record<string, unknown>): void {
	process.stderr.write(logLine(level, logger, message, extra) + '\n');
}

/** What a line says about a thrown value; log these fields rather than the Error itself. */
export function exceptionFields(error: unknown): { exc_type: string; exc_message: string; traceback: string | null } {
	if (error instanceof Error) return { exc_type: error.name, exc_message: error.message, traceback: error.stack ?? null };
	return { exc_type: typeof error, exc_message: String(error), traceback: null };
}
```

Write to `process.stdout` instead when the platform collects stdout; keep one stream per service.

## redact.ts

`contentFields` names the request body fields that hold user text or credentials in your API.

```ts
export const OMITTED = '[omitted]';
/** Shorter lines of a multi-line value are too common to take out on their own. */
const MIN_LINE = 4;

function variants(value: string): string[] {
	const normalised = value.replace(/\r\n?/g, '\n');
	const lines = normalised.split('\n').map((line) => line.trim()).filter((line) => line.length >= MIN_LINE);
	return [value, value.trim(), normalised, normalised.trim(), JSON.stringify(value).slice(1, -1), ...lines];
}

/** A request body's top-level fields: URL-encoded or multipart forms, and JSON whatever the
 *  declared content type; null for anything else. Pass a copy (`request.clone()`). */
export async function bodyFields(copy: Request): Promise<Record<string, unknown> | null> {
	const type = copy.headers.get('content-type') ?? '';
	try {
		if (/application\/x-www-form-urlencoded|multipart\/form-data/.test(type)) return Object.fromEntries((await copy.formData()).entries());
		const parsed: unknown = JSON.parse(await copy.text());
		return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
	} catch {
		return null;
	}
}

/** The texts to take out for one request: its content fields and its token. */
export function secretsOf(fields: Record<string, unknown> | null, token: string | undefined, contentFields: readonly string[]): string[] {
	const values = contentFields.map((field) => fields?.[field]).filter((value): value is string => typeof value === 'string');
	if (token) values.push(token);
	const found = new Set(values.flatMap(variants).filter((value) => value.trim()));
	// Longest first, so a value inside a longer one does not leave the rest of it behind.
	return [...found].sort((a, b) => b.length - a.length);
}

export function redact(text: string, secrets: string[]): string {
	let result = text
		// Node quotes an argument a child process refused after "Received".
		.replace(/(\. Received ).*$/gm, `$1${OMITTED}`)
		// JSON.parse quotes the input it could not read, cut short with "..." when long.
		.replace(/"[^\n]*"(?:\.\.\.)? is not valid JSON/g, `"${OMITTED}" is not valid JSON`)
		// A URL keeps no query or fragment; a stack frame's line and column stay.
		.replace(/(\bhttps?:\/\/[^\s?#()'"]+)[?#][^\s()'"]*?((?::\d+){1,2})?(?=[)\s'"]|$)/gm, '$1$2');
	for (const secret of secrets) result = result.split(secret).join(OMITTED);
	return result;
}

/** Redact first, then cut: a secret split by the cut is no longer recognised. */
export const limited = (text: string, max: number) => (text.length > max ? `${text.slice(0, max)}…` : text);
```

## Request wrapper (any fetch-style framework)

`request-logging.ts`, for frameworks whose handlers take a `Request` and return a `Response` (Hono, Bun.serve, Next.js route handlers). Adapt `tokenOf` and `CONTENT_FIELDS` to your API: where the credential travels (header or cookie) and which body fields hold user text.

```ts
import { randomUUID } from 'node:crypto';
import { exceptionFields, log, withRequestId } from './log.ts';
import { bodyFields, limited, redact, secretsOf } from './redact.ts';

const REQUEST_ID = /^[\w.:-]{1,128}$/;
const CONTENT_FIELDS = ['password', 'text', 'note'] as const;
const MAX_REASON = 2000;

const tokenOf = (request: Request) => request.headers.get('authorization')?.replace(/^Bearer\s+/i, '') ?? undefined;

export function requestIdOf(request: Request): string {
	const given = request.headers.get('x-request-id');
	return given && REQUEST_ID.test(given) ? given : randomUUID();
}

/** Reads the body from a copy, only when a line needs it. Create it before the handler consumes the body. */
export function redactorFor(request: Request): (text: string) => Promise<string> {
	const copy = request.body ? request.clone() : null;
	const token = tokenOf(request);
	let secrets: Promise<string[]> | undefined;
	return async (text) => {
		secrets ??= (copy ? bodyFields(copy) : Promise.resolve(null)).then((fields) => secretsOf(fields, token, CONTENT_FIELDS));
		return redact(text, await secrets);
	};
}

/** Body field that carries a failure reason -> log field. `message` is the event name, so a body's
 *  `message` (SvelteKit's error body) is logged as `detail`. */
const REASON_FIELDS = { reason: 'reason', error: 'error', message: 'detail' } as const;

/** One ERROR line for a response with status 500 or above, with the reasons its JSON body gave. */
export async function logFailure(where: { method: string; path: string }, response: Response, redacted: (text: string) => Promise<string>) {
	const body = response.headers.get('content-type')?.includes('application/json')
		? await response.clone().json().catch(() => null)
		: null;
	const reasons: Record<string, string> = {};
	for (const [field, name] of Object.entries(REASON_FIELDS)) {
		if (typeof body?.[field] === 'string' && body[field]) reasons[name] = limited(await redacted(body[field]), MAX_REASON);
	}
	log('ERROR', 'app.http', 'http_error', { ...where, status: response.status, ...reasons });
}

export async function withRequestLogging(request: Request, handler: (request: Request) => Promise<Response>): Promise<Response> {
	const requestId = requestIdOf(request);
	const redacted = redactorFor(request);
	const where = { method: request.method, path: new URL(request.url).pathname };
	return withRequestId(requestId, async () => {
		let response: Response;
		try {
			response = await handler(request);
		} catch (error) {
			const { exc_type, exc_message, traceback } = exceptionFields(error);
			log('ERROR', 'app.http', 'unhandled_error', {
				...where,
				exc_type,
				exc_message: await redacted(exc_message),
				traceback: traceback && (await redacted(traceback))
			});
			log('ERROR', 'app.http', 'http_error', { ...where, status: 500 });
			return Response.json({ error: 'internal_error' }, { status: 500, headers: { 'x-request-id': requestId } });
		}
		if (response.status >= 500) await logFailure(where, response, redacted);
		return response;
	});
}
```

Add the fields that carry the failure reason in your API's error bodies to `REASON_FIELDS`.

## SvelteKit hooks

SvelteKit renders its own error page, so log there instead of returning a response; `handleError` can run outside `handle`'s context, so the id and redactor live on `event.locals`.

```ts
// src/hooks.server.ts
import { isHttpError, isRedirect } from '@sveltejs/kit';
import type { Handle, HandleServerError } from '@sveltejs/kit/hooks'; // SvelteKit 2: from '@sveltejs/kit'
import { exceptionFields, log, withRequestId } from '$lib/server/log';
import { logFailure, redactorFor, requestIdOf } from '$lib/server/request-logging';

export const handle: Handle = ({ event, resolve }) => {
	event.locals.requestId = requestIdOf(event.request);
	event.locals.redact = redactorFor(event.request);
	const where = { method: event.request.method, path: event.url.pathname };
	return withRequestId(event.locals.requestId, async () => {
		let response: Response;
		try {
			response = await resolve(event);
		} catch (error) {
			// Thrown before or around resolving: SvelteKit answers after this, where nothing else sees it.
			const status = isRedirect(error) ? 0 : isHttpError(error) ? error.status : 500;
			if (status >= 500) log('ERROR', 'app.http', 'http_error', { ...where, status });
			throw error;
		}
		if (response.status >= 500) await logFailure(where, response, event.locals.redact);
		return response;
	});
};

export const handleError: HandleServerError = async ({ kind, error, event }) => {
	if (kind !== 'unknown') return; // error() and not-found are expected
	// A failure before `handle` ran (loading a route module) has no id and no response line yet.
	const early = event.locals.requestId === undefined;
	event.locals.requestId ??= requestIdOf(event.request);
	event.locals.redact ??= redactorFor(event.request);
	const where = { method: event.request.method, path: event.url.pathname };
	const { exc_type, exc_message, traceback } = exceptionFields(error);
	const fields = {
		...where,
		exc_type,
		exc_message: await event.locals.redact(exc_message),
		traceback: traceback && (await event.locals.redact(traceback))
	};
	withRequestId(event.locals.requestId, () => {
		log('ERROR', 'app.http', 'unhandled_error', fields);
		if (early) log('ERROR', 'app.http', 'http_error', { ...where, status: 500 });
	});
};
```

Declare `requestId: string` and `redact: (text: string) => Promise<string>` in `App.Locals` (`src/app.d.ts`). `kind` exists from SvelteKit 3; on SvelteKit 2 check `status >= 500` instead.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Logging `error` objects directly | `JSON.stringify` gives `{}`; use `exceptionFields` |
| Calling the redactor after the handler read the body | Create it (it clones the request) before the handler runs |
| Cutting a field, then redacting it | Redact first, then `limited` |
| Expecting `AsyncLocalStorage` context in a framework's error hook | Keep the id on the request (`event.locals`) and re-enter with `withRequestId` |
| `console.log` with a template string | Not JSON and no `request_id`; use `log` |

## Not built in

Receiving browser error reports. When you add an endpoint for them, follow the client-report rule in SKILL.md: log only what the server can validate, never the report's free text.
