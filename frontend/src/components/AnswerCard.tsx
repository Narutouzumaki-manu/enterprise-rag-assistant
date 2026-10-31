// ─────────────────────────────────────────────────────────────────────────────
// AnswerCard.tsx — Assistant answer with trust badge, citations, and ratings.
//
// Rules:
//   - Render all text from API as plain text (no dangerouslySetInnerHTML).
//   - verification_status displayed via TrustBadge (NEVER display confidence).
//   - "I don't have sufficient evidence..." is a calm normal answer with no sources.
//   - "Please try again" variants show a "Try again" button that resends query.
//   - CitationCards shown under answer.
//   - aria-live="polite" announces the finished answer once, not each token.
//   - RatingButtons enabled once message_id is available.
// ─────────────────────────────────────────────────────────────────────────────

import { TrustBadge } from './TrustBadge';
import { CitationCard } from './CitationCard';
import { RatingButtons } from './RatingButtons';
import type { Citation, VerificationStatus } from '../api/types';

interface AnswerCardProps {
  content: string;
  verificationStatus: VerificationStatus | null;
  citations: Citation[];
  messageId: string | null;
  isLive?: boolean;
  onRetryQuestion?: () => void;
  messageIdFailed?: boolean;
  onReloadRating?: () => void;
}

export function AnswerCard({
  content,
  verificationStatus,
  citations,
  messageId,
  isLive = false,
  onRetryQuestion,
  messageIdFailed = false,
  onReloadRating,
}: AnswerCardProps) {
  // Check if answer is a retriable honest response (e.g. "Please try again.")
  const isRetriable =
    !isLive &&
    (content.includes('Please try again') || content.includes('please try again'));

  return (
    <article
      className="space-y-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl p-5 shadow-sm"
      aria-label="Assistant response"
    >
      {/* Header: Trust Badge (shown when verification status is available) */}
      {verificationStatus && (
        <div className="flex items-center justify-between">
          <TrustBadge status={verificationStatus} />
        </div>
      )}

      {/* Answer content: plain text with preserved whitespace.
          aria-live="polite" announces the full finished answer once (when !isLive),
          never announcing every streaming word token. */}
      <div
        className="text-sm text-gray-800 dark:text-gray-100 leading-relaxed whitespace-pre-wrap break-words"
        aria-live={!isLive ? 'polite' : 'off'}
      >
        {content || (isLive ? '' : 'No content.')}
      </div>

      {/* "Try again" button for retriable answers */}
      {isRetriable && onRetryQuestion && (
        <div className="pt-1">
          <button
            type="button"
            onClick={onRetryQuestion}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 hover:bg-blue-100 dark:hover:bg-blue-900/60 border border-blue-200 dark:border-blue-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            <span>Try again</span>
          </button>
        </div>
      )}

      {/* Citations section */}
      {!isLive && citations && citations.length > 0 && (
        <section aria-labelledby={`citations-${messageId ?? 'live'}`} className="pt-2 space-y-2 border-t border-gray-100 dark:border-gray-800">
          <h4
            id={`citations-${messageId ?? 'live'}`}
            className="text-[11px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider"
          >
            Sources ({citations.length})
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {citations.map((c) => (
              <CitationCard key={c.chunk_id} citation={c} />
            ))}
          </div>
        </section>
      )}

      {/* Rating actions: enabled once message_id is available */}
      {!isLive && (
        <div className="border-t border-gray-100 dark:border-gray-800 pt-1">
          <RatingButtons
            messageId={messageId}
            messageIdFailed={messageIdFailed}
            onReloadRating={onReloadRating}
          />
        </div>
      )}
    </article>
  );
}

