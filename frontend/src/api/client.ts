// ─────────────────────────────────────────────────────────────────────────────
// client.ts — typed fetch wrapper with:
//   • Automatic Authorization: Bearer <token> injection
//   • Error-body → ApiError mapping (shows server's "error" text to users)
//   • 401 handling: clear token + call the registered unauthorized handler
//   • X-Request-ID extraction
//   • Network-failure → DEPENDENCY_UNAVAILABLE mapping
//   • Retry-After header parsing
// ─────────────────────────────────────────────────────────────────────────────

import type { ApiError, ErrorCode } from './types';
import { getToken, clearToken } from './tokenStore';

// ─── Unauthorized handler ─────────────────────────────────────────────────────
//
// The React auth provider (Phase B) registers its own handler via
// registerUnauthorizedHandler().  Until then, a sensible default navigates
// via window.location so the app still works even before the provider mounts.

type UnauthorizedHandler = () => void;

let _unauthorizedHandler: UnauthorizedHandler = () => {
  const from = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.replace(`/login?from=${from}&expired=1`);
};

/**
 * Register a handler that is called whenever any request receives a 401.
 * The handler should clear the TanStack Query cache, abort active streams,
 * and navigate to /login.  Called AFTER the token has already been cleared.
 */
export function registerUnauthorizedHandler(handler: UnauthorizedHandler): void {
  _unauthorizedHandler = handler;
}

// ─── Error class ─────────────────────────────────────────────────────────────

/** Thrown by apiFetch (and its helpers) on any non-2xx response or network failure. */
export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(apiError.error);
    this.name = 'ApiRequestError';
    this.apiError = apiError;
  }
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

function parseRetryAfter(headers: Headers): number | null {
  const val = headers.get('Retry-After');
  if (!val) return null;
  const secs = parseInt(val, 10);
  return Number.isFinite(secs) ? secs : null;
}

// ─── Auth header helper (also used by useChatStream / XHR uploads) ────────────

/**
 * Returns an object with the Authorization header if a token is stored,
 * or an empty object if the user is not logged in.
 * Use this when calling fetch() directly (e.g. for streaming or XHR upload).
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────

/**
 * Authenticated fetch wrapper.  Injects the bearer token, maps every
 * non-2xx response to an ApiRequestError, and handles 401 globally.
 *
 * For streaming (POST /chat/stream) use fetch() + getAuthHeaders() directly.
 * For XHR uploads use XMLHttpRequest + getAuthHeaders() directly.
 */
export async function apiFetch<T>(
  url: string,
  options: RequestInit = {},
): Promise<{ data: T; requestId: string | null }> {
  // Merge caller headers with the Authorization header
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    // Network error / backend not reachable
    const apiError: ApiError = {
      error: 'Could not reach the server. Please check your connection.',
      code: 'DEPENDENCY_UNAVAILABLE',
      status: 0,
      requestId: null,
      retryAfter: null,
    };
    throw new ApiRequestError(apiError);
  }

  const requestId = response.headers.get('X-Request-ID');
  const retryAfter = parseRetryAfter(response.headers);

  if (response.ok) {
    // 204 No Content — body is empty (DELETE endpoints)
    if (response.status === 204) {
      return { data: undefined as unknown as T, requestId };
    }
    const data = (await response.json()) as T;
    return { data, requestId };
  }

  // ── Non-2xx: parse the standard error body ────────────────────────────────
  let errorBody: { error: string; code: ErrorCode } = {
    error: 'An unexpected error occurred.',
    code: 'INTERNAL_ERROR',
  };
  try {
    errorBody = (await response.json()) as { error: string; code: ErrorCode };
  } catch {
    // Body is not JSON (e.g. a 500 from an intermediate proxy) — use defaults
  }

  const apiError: ApiError = {
    error: errorBody.error,
    code: errorBody.code,
    status: response.status,
    requestId,
    retryAfter,
  };

  if (response.status === 401) {
    clearToken();
    _unauthorizedHandler();
  }

  throw new ApiRequestError(apiError);
}

// ─── Convenience helpers ──────────────────────────────────────────────────────

export async function apiGet<T>(
  url: string,
): Promise<{ data: T; requestId: string | null }> {
  return apiFetch<T>(url, { method: 'GET' });
}

export async function apiPost<T>(
  url: string,
  body: unknown,
): Promise<{ data: T; requestId: string | null }> {
  return apiFetch<T>(url, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * DELETE helper — expects 204 No Content from the server.
 * Throws ApiRequestError on 403 (not uploader), 409 (still processing),
 * or 503 (index cleanup failed).
 */
export async function apiDelete(
  url: string,
): Promise<{ requestId: string | null }> {
  const { requestId } = await apiFetch<void>(url, { method: 'DELETE' });
  return { requestId };
}

