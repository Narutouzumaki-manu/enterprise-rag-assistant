// ─────────────────────────────────────────────────────────────────────────────
// TrustBadge.tsx — Displays the verification status of an assistant answer.
//
// Rules:
//   - Icon AND text AND colour (colour never the only signal).
//   - verified: neutral/green, "Found in your documents".
//   - partially_verified: amber caution, "Some parts could not be fully verified".
//   - unverified: red/strong warning, never styled like verified.
//   - NEVER display confidence anywhere.
//   - NEVER write "correct", "accurate" or "guaranteed".
// ─────────────────────────────────────────────────────────────────────────────

import type { VerificationStatus } from '../api/types';

interface TrustBadgeProps {
  status: VerificationStatus;
}

export function TrustBadge({ status }: TrustBadgeProps) {
  switch (status) {
    case 'verified':
      return (
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-300 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800"
          role="status"
          aria-label="Verification status: Found in your documents"
        >
          <svg
            className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          <span>Found in your documents</span>
        </span>
      );

    case 'partially_verified':
      return (
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-300 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800"
          role="status"
          aria-label="Verification status: Some parts could not be fully verified"
        >
          <svg
            className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
          <span>Some parts could not be fully verified</span>
        </span>
      );

    case 'unverified':
      return (
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-800 border border-rose-300 dark:bg-rose-950/50 dark:text-rose-300 dark:border-rose-800"
          role="status"
          aria-label="Verification status: Unverified in documents"
        >
          <svg
            className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span>Unverified in documents</span>
        </span>
      );
  }
}

