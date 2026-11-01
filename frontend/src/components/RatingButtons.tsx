// ─────────────────────────────────────────────────────────────────────────────
// RatingButtons.tsx — Feedback rating (thumbs up / thumbs down) & optional comment.
//
// Rules:
//   - POST /feedback { message_id, rating: 1 | -1, comment?: string (max 1000) }
//   - Only enabled once message_id is available (refetched after streaming).
//   - Rating again replaces the previous rating.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, type FormEvent } from 'react';
import { apiPost } from '../api/client';
import type { FeedbackResponse, Rating } from '../api/types';

interface RatingButtonsProps {
  messageId: string | null;
  initialRating?: Rating | null;
  messageIdFailed?: boolean;
  onReloadRating?: () => void;
  onReloadMessageId?: () => void;
}

export function RatingButtons({
  messageId,
  initialRating = null,
  messageIdFailed = false,
  onReloadRating,
  onReloadMessageId,
}: RatingButtonsProps) {
  const [currentRating, setCurrentRating] = useState<Rating | null>(initialRating);
  const [comment, setComment] = useState('');
  const [isCommentOpen, setIsCommentOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const handleRate = async (rating: Rating) => {
    if (!messageId || isSubmitting) return;

    setIsSubmitting(true);
    setFeedbackError(null);
    try {
      await apiPost<FeedbackResponse>('/feedback', {
        message_id: messageId,
        rating,
        ...(comment.trim() ? { comment: comment.trim().slice(0, 1000) } : {}),
      });
      setCurrentRating(rating);
    } catch {
      setFeedbackError('Failed to record rating. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCommentSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!messageId || currentRating === null || isSubmitting) return;

    setIsSubmitting(true);
    setFeedbackError(null);
    try {
      await apiPost<FeedbackResponse>('/feedback', {
        message_id: messageId,
        rating: currentRating,
        comment: comment.trim().slice(0, 1000),
      });
      setIsCommentOpen(false);
    } catch {
      setFeedbackError('Failed to save comment.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const isEnabled = messageId !== null && !isSubmitting;

  return (
    <div className="pt-2 text-xs text-gray-600 dark:text-gray-400">
      <div className="flex items-center gap-2">
        <span className="text-xs">Was this helpful?</span>

        <button
          type="button"
          disabled={!isEnabled}
          onClick={() => handleRate(1)}
          aria-label="Helpful"
          aria-pressed={currentRating === 1}
          className={`p-2 min-h-[40px] min-w-[40px] inline-flex items-center justify-center rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 disabled:opacity-40 disabled:cursor-not-allowed ${
            currentRating === 1
              ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/40 dark:text-blue-300 font-bold'
              : 'hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'
          }`}
        >
          <svg
            className="w-4 h-4"
            fill={currentRating === 1 ? 'currentColor' : 'none'}
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="1.75"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5"
            />
          </svg>
        </button>

        <button
          type="button"
          disabled={!isEnabled}
          onClick={() => handleRate(-1)}
          aria-label="Not helpful"
          aria-pressed={currentRating === -1}
          className={`p-2 min-h-[40px] min-w-[40px] inline-flex items-center justify-center rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 disabled:opacity-40 disabled:cursor-not-allowed ${
            currentRating === -1
              ? 'text-rose-600 bg-rose-50 dark:bg-rose-900/40 dark:text-rose-300 font-bold'
              : 'hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'
          }`}
        >
          <svg
            className="w-4 h-4"
            fill={currentRating === -1 ? 'currentColor' : 'none'}
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="1.75"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018a2 2 0 01.485.06l3.76.94m-7 10v5a2 2 0 002 2h.096c.5 0 .905-.405.905-.904 0-.715.211-1.413.608-2.008L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5"
            />
          </svg>
        </button>

        {currentRating !== null && (
          <button
            type="button"
            onClick={() => setIsCommentOpen((prev) => !prev)}
            className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 underline underline-offset-2 ml-1"
          >
            {isCommentOpen ? 'Close comment' : 'Add feedback comment'}
          </button>
        )}
      </div>

      {isCommentOpen && (
        <form onSubmit={handleCommentSubmit} className="mt-2 space-y-2">
          <label htmlFor={`comment-${messageId}`} className="sr-only">
            Feedback comment
          </label>
          <textarea
            id={`comment-${messageId}`}
            rows={2}
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional comment (max 1000 characters)..."
            className="w-full text-xs p-2 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-600 dark:text-gray-400">
              {comment.length}/1000
            </span>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-2.5 py-1 text-xs font-medium rounded bg-gray-900 hover:bg-gray-800 dark:bg-gray-700 dark:hover:bg-gray-600 text-white disabled:opacity-50"
            >
              Submit comment
            </button>
          </div>
        </form>
      )}

      {feedbackError && (
        <p className="text-xs text-rose-600 dark:text-rose-400 mt-1">
          {feedbackError}
        </p>
      )}

      {messageIdFailed && !messageId && (
        <div className="flex items-center gap-2 mt-2 pt-1 text-xs text-gray-500 dark:text-gray-400">
          <span>Rating is unavailable right now</span>
          {(onReloadRating || onReloadMessageId) && (
            <button
              type="button"
              onClick={onReloadRating ?? onReloadMessageId}
              className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300 font-medium focus:outline-none"
            >
              Reload to rate
            </button>
          )}
        </div>
      )}
    </div>
  );
}

