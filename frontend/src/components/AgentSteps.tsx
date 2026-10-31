// ─────────────────────────────────────────────────────────────────────────────
// AgentSteps.tsx — Transparency panel showing what the system is doing.
//
// Rules:
//   - Live while streaming: progressing list with the last line marked in progress.
//   - Show elapsed time and the note "Checking the answer before showing it".
//   - Lines mentioning "searching again" show a caution icon (feature, not error).
//   - Checkmark when done. Never an empty or infinite spinner.
//   - After answer arrives: collapsed to "N steps", expandable by clicking.
//   - Reopening a session renders from saved trace[].
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react';

interface AgentStepsProps {
  steps: Array<{ step_type: string; content: string }>;
  isLive: boolean;
  startTime?: number | null;
}

export function AgentSteps({ steps, isLive, startTime }: AgentStepsProps) {
  // If not live (saved answer or finished stream), start collapsed
  const [isOpen, setIsOpen] = useState(isLive);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // If live status changes to true, ensure it's open
  useEffect(() => {
    if (isLive) {
      setIsOpen(true);
    }
  }, [isLive]);

  // Elapsed timer while live
  useEffect(() => {
    if (!isLive || !startTime) {
      setElapsedSeconds(0);
      return;
    }

    const interval = setInterval(() => {
      const now = Date.now();
      setElapsedSeconds(Math.max(0, Math.floor((now - startTime) / 1000)));
    }, 500);

    return () => clearInterval(interval);
  }, [isLive, startTime]);

  if (!steps || steps.length === 0) {
    if (!isLive) return null;
    return (
      <div className="my-2 p-3 bg-gray-50 dark:bg-gray-800/60 rounded-lg border border-gray-200 dark:border-gray-700/80 text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
        <svg
          className="animate-spin h-4 w-4 text-blue-600 dark:text-blue-400 shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          ></circle>
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v8H4z"
          ></path>
        </svg>
        <span>Starting research... (Checking the answer before showing it)</span>
      </div>
    );
  }

  const stepCount = steps.length;
  const isRetry = (text: string) => text.toLowerCase().includes('searching again');

  // When finished (not live), render collapsible summary
  if (!isLive) {
    return (
      <div className="my-2 text-xs">
        <button
          type="button"
          onClick={() => setIsOpen((prev) => !prev)}
          aria-expanded={isOpen}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <svg
            className={`w-3.5 h-3.5 transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <span>
            {stepCount} {stepCount === 1 ? 'step' : 'steps'}
          </span>
        </button>

        {isOpen && (
          <ol className="mt-2 pl-4 border-l-2 border-gray-200 dark:border-gray-700 space-y-1.5">
            {steps.map((step, idx) => {
              const retry = isRetry(step.content);
              return (
                <li key={idx} className="flex items-start gap-2 text-gray-600 dark:text-gray-400">
                  {retry ? (
                    <span
                      title="Searching again for unsupported claim"
                      className="text-amber-500 font-bold shrink-0 text-sm leading-none mt-0.5"
                      aria-label="Caution: searching again"
                    >
                      ⚠️
                    </span>
                  ) : (
                    <span
                      className="text-emerald-600 dark:text-emerald-400 shrink-0 font-bold"
                      aria-label="Completed step"
                    >
                      ✓
                    </span>
                  )}
                  <span>{step.content}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    );
  }

  // Live streaming view
  return (
    <div
      role="region"
      aria-label="Agent progress steps"
      className="my-3 p-3.5 bg-blue-50/60 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/40 rounded-xl space-y-2.5"
    >
      <div className="flex items-center justify-between text-xs text-blue-900 dark:text-blue-200 font-medium pb-1 border-b border-blue-100 dark:border-blue-900/40">
        <div className="flex items-center gap-2">
          <svg
            className="animate-spin h-3.5 w-3.5 text-blue-600 dark:text-blue-400"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            ></circle>
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            ></path>
          </svg>
          <span>Researching documents...</span>
        </div>
        <span className="text-gray-500 dark:text-gray-400 font-mono">
          {elapsedSeconds}s elapsed
        </span>
      </div>

      <p className="text-[11px] text-gray-500 dark:text-gray-400 italic">
        Checking the answer before showing it
      </p>

      <ol className="space-y-1.5 text-xs">
        {steps.map((step, idx) => {
          const isCurrent = idx === steps.length - 1;
          const retry = isRetry(step.content);

          return (
            <li
              key={idx}
              className={`flex items-start gap-2 ${
                isCurrent
                  ? 'text-gray-900 dark:text-white font-medium'
                  : 'text-gray-600 dark:text-gray-400'
              }`}
            >
              {isCurrent ? (
                <svg
                  className="animate-spin h-3.5 w-3.5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-label="In progress"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  ></circle>
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  ></path>
                </svg>
              ) : retry ? (
                <span
                  title="Searching again for unsupported claim"
                  className="text-amber-500 font-bold shrink-0 text-sm leading-none mt-0.5"
                  aria-label="Caution: searching again"
                >
                  ⚠️
                </span>
              ) : (
                <span
                  className="text-emerald-600 dark:text-emerald-400 shrink-0 font-bold"
                  aria-label="Completed step"
                >
                  ✓
                </span>
              )}
              <span>{step.content}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

