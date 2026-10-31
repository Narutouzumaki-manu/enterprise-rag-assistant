import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  apiFetch,
  apiPost,
  apiDelete,
  registerUnauthorizedHandler,
  ApiRequestError,
} from '../api/client';
import { setToken, getToken, clearToken } from '../api/tokenStore';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Build a mock fetch that resolves once with the given Response. */
function stubFetch(response: Response): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValueOnce(response);
  vi.stubGlobal('fetch', mock);
  return mock;
}

function jsonResponse(
  body: unknown,
  init: ResponseInit = { status: 200 },
): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

// ─── Setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  clearToken();
  // Replace the default handler (which calls window.location.replace) with a
  // no-op so tests never accidentally navigate away.
  registerUnauthorizedHandler(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearToken();
  // Reset to no-op so leftover handler state doesn't leak between test files.
  registerUnauthorizedHandler(() => {});
});

// ─── apiFetch — request headers ───────────────────────────────────────────────

describe('apiFetch — request headers', () => {
  it('injects Authorization header when a token is stored', async () => {
    setToken('tok-123');
    const mock = stubFetch(jsonResponse({ ok: true }));

    await apiFetch('/test');

    const [, opts] = mock.mock.calls[0] as [string, RequestInit & { headers: Headers }];
    expect(opts.headers.get('Authorization')).toBe('Bearer tok-123');
  });

  it('omits Authorization header when no token is stored', async () => {
    const mock = stubFetch(jsonResponse({ ok: true }));

    await apiFetch('/test');

    const [, opts] = mock.mock.calls[0] as [string, RequestInit & { headers: Headers }];
    expect(opts.headers.get('Authorization')).toBeNull();
  });

  it('forwards caller-supplied headers alongside the auth header', async () => {
    setToken('tok-abc');
    const mock = stubFetch(jsonResponse({ ok: true }));

    await apiFetch('/test', { headers: { 'X-Custom': 'yes' } });

    const [, opts] = mock.mock.calls[0] as [string, RequestInit & { headers: Headers }];
    expect(opts.headers.get('X-Custom')).toBe('yes');
    expect(opts.headers.get('Authorization')).toBe('Bearer tok-abc');
  });
});

// ─── apiFetch — successful responses ─────────────────────────────────────────

describe('apiFetch — successful responses', () => {
  it('returns parsed data and requestId on 200', async () => {
    stubFetch(
      new Response(JSON.stringify({ value: 42 }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': 'req-abc',
        },
      }),
    );

    const { data, requestId } = await apiFetch<{ value: number }>('/test');
    expect(data).toEqual({ value: 42 });
    expect(requestId).toBe('req-abc');
  });

  it('returns null requestId when X-Request-ID header is absent', async () => {
    stubFetch(jsonResponse({ ok: true }));
    const { requestId } = await apiFetch('/test');
    expect(requestId).toBeNull();
  });

  it('handles 204 No Content (DELETE) — returns undefined data without parsing', async () => {
    stubFetch(new Response(null, { status: 204 }));
    const { data } = await apiFetch<void>('/resource/1', { method: 'DELETE' });
    expect(data).toBeUndefined();
  });

  it('handles 201 Created — returns body correctly', async () => {
    stubFetch(jsonResponse({ session_id: 's1' }, { status: 201 }));
    const { data } = await apiFetch<{ session_id: string }>('/sessions', { method: 'POST' });
    expect(data.session_id).toBe('s1');
  });
});

// ─── apiFetch — error mapping ─────────────────────────────────────────────────

describe('apiFetch — error mapping', () => {
  it('throws ApiRequestError with error, code, status and requestId on 4xx', async () => {
    stubFetch(
      new Response(
        JSON.stringify({ error: 'File too large', code: 'FILE_TOO_LARGE' }),
        { status: 413, headers: { 'X-Request-ID': 'req-413' } },
      ),
    );

    let caught: unknown;
    try {
      await apiFetch('/documents/upload');
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeInstanceOf(ApiRequestError);
    const err = (caught as ApiRequestError).apiError;
    expect(err.error).toBe('File too large');
    expect(err.code).toBe('FILE_TOO_LARGE');
    expect(err.status).toBe(413);
    expect(err.requestId).toBe('req-413');
  });

  it('uses default error text when the response body is not valid JSON', async () => {
    stubFetch(new Response('Internal Server Error', { status: 500 }));

    let caught: unknown;
    try {
      await apiFetch('/test');
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeInstanceOf(ApiRequestError);
    const err = (caught as ApiRequestError).apiError;
    expect(err.code).toBe('INTERNAL_ERROR');
    expect(typeof err.error).toBe('string');
  });

  it('parses Retry-After header (seconds) on 429', async () => {
    stubFetch(
      new Response(
        JSON.stringify({ error: 'Too many requests', code: 'RATE_LIMITED' }),
        { status: 429, headers: { 'Retry-After': '30' } },
      ),
    );

    let caught: unknown;
    try { await apiFetch('/chat/stream'); } catch (e) { caught = e; }
    expect((caught as ApiRequestError).apiError.retryAfter).toBe(30);
  });

  it('sets retryAfter to null when Retry-After header is absent', async () => {
    stubFetch(
      jsonResponse({ error: 'Not found', code: 'NOT_FOUND' }, { status: 404 }),
    );

    let caught: unknown;
    try { await apiFetch('/sessions/x'); } catch (e) { caught = e; }
    expect((caught as ApiRequestError).apiError.retryAfter).toBeNull();
  });
});

// ─── apiFetch — 401 handling ──────────────────────────────────────────────────

describe('apiFetch — 401 handling', () => {
  it('clears the stored token on 401', async () => {
    setToken('valid-token');
    stubFetch(
      jsonResponse(
        { error: 'Unauthorized', code: 'UNAUTHENTICATED' },
        { status: 401 },
      ),
    );

    await expect(apiFetch('/sessions')).rejects.toBeInstanceOf(ApiRequestError);
    expect(getToken()).toBeNull();
  });

  it('calls the registered unauthorized handler exactly once on 401', async () => {
    const handler = vi.fn();
    registerUnauthorizedHandler(handler);

    stubFetch(
      jsonResponse(
        { error: 'Unauthorized', code: 'UNAUTHENTICATED' },
        { status: 401 },
      ),
    );

    await expect(apiFetch('/sessions')).rejects.toBeInstanceOf(ApiRequestError);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('does NOT call the unauthorized handler on other error codes (403)', async () => {
    const handler = vi.fn();
    registerUnauthorizedHandler(handler);

    stubFetch(
      jsonResponse({ error: 'Forbidden', code: 'FORBIDDEN' }, { status: 403 }),
    );

    await expect(apiFetch('/sessions')).rejects.toBeInstanceOf(ApiRequestError);
    expect(handler).not.toHaveBeenCalled();
  });

  it('throws ApiRequestError even after calling the handler', async () => {
    stubFetch(
      jsonResponse(
        { error: 'Unauthorized', code: 'UNAUTHENTICATED' },
        { status: 401 },
      ),
    );

    await expect(apiFetch('/sessions')).rejects.toBeInstanceOf(ApiRequestError);
  });
});

// ─── apiFetch — network errors ────────────────────────────────────────────────

describe('apiFetch — network errors', () => {
  it('wraps a TypeError (Failed to fetch) as DEPENDENCY_UNAVAILABLE with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')));

    let caught: unknown;
    try { await apiFetch('/sessions'); } catch (e) { caught = e; }

    expect(caught).toBeInstanceOf(ApiRequestError);
    const err = (caught as ApiRequestError).apiError;
    expect(err.code).toBe('DEPENDENCY_UNAVAILABLE');
    expect(err.status).toBe(0);
    expect(err.requestId).toBeNull();
  });
});

// ─── apiPost ──────────────────────────────────────────────────────────────────

describe('apiPost', () => {
  it('sends POST with JSON body and correct Content-Type', async () => {
    const mock = stubFetch(
      new Response(JSON.stringify({ session_id: 's1' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await apiPost('/sessions', {});

    const [url, opts] = mock.mock.calls[0] as [string, RequestInit & { headers: Headers }];
    expect(url).toBe('/sessions');
    expect(opts.method).toBe('POST');
    expect(opts.headers.get('Content-Type')).toBe('application/json');
  });

  it('serialises the request body as JSON', async () => {
    const mock = stubFetch(jsonResponse({ ok: true }));
    await apiPost('/auth/login', { email: 'a@b.com', password: 'secret' });

    const [, opts] = mock.mock.calls[0] as [string, RequestInit];
    expect(opts.body).toBe(JSON.stringify({ email: 'a@b.com', password: 'secret' }));
  });
});

// ─── apiDelete ────────────────────────────────────────────────────────────────

describe('apiDelete', () => {
  it('sends DELETE and returns requestId from the header', async () => {
    const mock = stubFetch(
      new Response(null, { status: 204, headers: { 'X-Request-ID': 'del-req' } }),
    );

    const { requestId } = await apiDelete('/documents/doc-1');

    const [url, opts] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/documents/doc-1');
    expect(opts.method).toBe('DELETE');
    expect(requestId).toBe('del-req');
  });

  it('throws ApiRequestError on 403 (not uploader)', async () => {
    stubFetch(
      jsonResponse({ error: 'Forbidden', code: 'FORBIDDEN' }, { status: 403 }),
    );

    await expect(apiDelete('/documents/doc-1')).rejects.toBeInstanceOf(
      ApiRequestError,
    );
  });

  it('throws ApiRequestError on 409 (still processing)', async () => {
    stubFetch(
      jsonResponse({ error: 'Conflict', code: 'CONFLICT' }, { status: 409 }),
    );

    await expect(apiDelete('/documents/doc-1')).rejects.toBeInstanceOf(
      ApiRequestError,
    );
  });
});

