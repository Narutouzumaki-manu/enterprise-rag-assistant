// ─────────────────────────────────────────────────────────────────────────────
// ErrorState.tsx — Error presentations.
//
// Rules:
//   - Full-page unavailable screen ONLY for DEPENDENCY_UNAVAILABLE or server down.
//   - Shows human-readable message, request ID, and Retry button.
//   - InlineErrorNotice for temporary 503 AGENT_BUSY and 429 with Retry-After.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';
import type { HealthResponse } from '../api/types';

interface ServiceUnavailablePageProps {
  requestId?: string | null;
  onRetry: () => void;
}

export function ServiceUnavailablePage({
  requestId,
  onRetry,
}: ServiceUnavailablePageProps) {
  const [healthInfo, setHealthInfo] = useState<HealthResponse | null>(null);

  // Fetch /health once when screen opens (not polled)
  useEffect(() => {
    let active = true;
    void apiGet<HealthResponse>('/health')
      .then((res) => {
        if (active) setHealthInfo(res.data);
      })
      .catch(() => {
        // Ignore health check failure if whole server is down
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center p-4">
      <div className="max-w-md w-full text-center space-y-6 bg-white dark:bg-gray-900 p-8 rounded-2xl shadow-sm border border-gray-200 dark:border-gray-800">
        <div className="mx-auto w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-950/50 flex items-center justify-center text-amber-600 dark:text-amber-400">
          <svg
            className="w-6 h-6"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>

        <div className="space-y-2">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Service Temporarily Unavailable
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            A backend dependency is currently unavailable. Please try again in a few moments.
          </p>
        </div>

        {healthInfo?.checks && (
          <div className="text-xs text-left bg-gray-50 dark:bg-gray-800/60 p-3 rounded-lg border border-gray-200 dark:border-gray-700/60 space-y-1">
            <span className="font-semibold text-gray-700 dark:text-gray-300">
              System checks:
            </span>
            <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
              {Object.entries(healthInfo.checks).map(([key, val]) => (
                <li key={key} className="flex justify-between">
                  <span className="capitalize">{key}:</span>
                  <span
                    className={
                      val === 'ok'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-amber-600 dark:text-amber-400 font-medium'
                    }
                  >
                    {val}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {requestId && (
          <p className="text-[11px] text-gray-400 font-mono">
            Request ID: {requestId}
          </p>
        )}

        <button
          type="button"
          onClick={onRetry}
          className="w-full py-2.5 px-4 text-sm font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

interface InlineErrorNoticeProps {
  error: string;
  retryAfterSeconds?: number | null;
  onRetry: () => void;
  requestId?: string | null;
  buttonLabel?: string;
}

export function InlineErrorNotice({
  error,
  retryAfterSeconds,
  onRetry,
  requestId,
  buttonLabel = 'Try again',
}: InlineErrorNoticeProps) {
  const [countdown, setCountdown] = useState<number | null>(
    retryAfterSeconds && retryAfterSeconds > 0 ? retryAfterSeconds : null,
  );

  useEffect(() => {
    if (retryAfterSeconds && retryAfterSeconds > 0) {
      setCountdown(retryAfterSeconds);
      const interval = setInterval(() => {
        setCountdown((prev) => {
          if (prev === null || prev <= 1) {
            clearInterval(interval);
            return null;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [retryAfterSeconds]);

  return (
    <div
      role="alert"
      className="p-3.5 my-2 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/80 text-amber-900 dark:text-amber-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs"
    >
      <div className="space-y-1">
        <p className="font-medium">{error}</p>
        {countdown !== null && (
          <p className="text-amber-700 dark:text-amber-300">
            Please wait {countdown}s before trying again.
          </p>
        )}
        {requestId && (
          <p className="text-[11px] font-mono text-gray-500 dark:text-gray-400">
            Request ID: {requestId}
          </p>
        )}
      </div>

      <button
        type="button"
        disabled={countdown !== null}
        onClick={onRetry}
        className="px-3 py-1.5 font-semibold rounded bg-amber-600 hover:bg-amber-700 text-white focus:outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-50 disabled:cursor-not-allowed shrink-0 transition-colors"
      >
        {countdown !== null ? `Wait ${countdown}s` : buttonLabel}
      </button>
    </div>
  );
}

