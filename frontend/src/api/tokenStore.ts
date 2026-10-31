// ─────────────────────────────────────────────────────────────────────────────
// tokenStore.ts — in-memory + sessionStorage token management.
//
// Rules (from the spec):
//  - Keep the token in memory AND sessionStorage (survives a page refresh;
//    cleared when the tab closes because sessionStorage is tab-scoped).
//  - Never use localStorage.
//  - Never put the token in a URL or log it.
// ─────────────────────────────────────────────────────────────────────────────

const SESSION_STORAGE_KEY = 'rag_token';

/** In-memory copy; avoids redundant sessionStorage reads on the hot path. */
let _memoryToken: string | null = null;

/**
 * Return the current access token, or null if not logged in.
 * Checks memory first, falls back to sessionStorage on a page refresh.
 */
export function getToken(): string | null {
  if (_memoryToken !== null) return _memoryToken;
  try {
    const stored = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (stored !== null) _memoryToken = stored;
    return stored;
  } catch {
    // sessionStorage unavailable (e.g. private-browsing restrictions)
    return null;
  }
}

/** Persist a new token to both memory and sessionStorage. */
export function setToken(token: string): void {
  _memoryToken = token;
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, token);
  } catch {
    // Keep in memory only if sessionStorage is unavailable
  }
}

/**
 * Erase the token from both memory and sessionStorage.
 * Called on explicit logout and on any 401 response.
 */
export function clearToken(): void {
  _memoryToken = null;
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Nothing to do
  }
}

