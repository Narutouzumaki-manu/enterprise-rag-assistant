// ─────────────────────────────────────────────────────────────────────────────
// streamAbort.ts — Registry for active stream AbortControllers.
// Allows logout and 401 handlers to immediately abort any in-flight SSE stream.
// ─────────────────────────────────────────────────────────────────────────────

const activeControllers = new Set<AbortController>();

/**
 * Register an AbortController for an active chat stream.
 * Returns an unregister function to call when the stream completes or errors.
 */
export function registerStreamAbortController(
  controller: AbortController,
): () => void {
  activeControllers.add(controller);
  return () => {
    activeControllers.delete(controller);
  };
}

/**
 * Abort all active chat streams.
 * Called during user logout or session expiration (401).
 */
export function abortAllActiveStreams(): void {
  for (const controller of activeControllers) {
    try {
      controller.abort();
    } catch {
      // Ignore if already aborted
    }
  }
  activeControllers.clear();
}

