// ─────────────────────────────────────────────────────────────────────────────
// CitationCard.tsx — Quotation preview for a citation source.
//
// Rules:
//   - Show "source_file, p. N" or "Document no longer available" if null.
//   - text_snippet (max 200 chars, may start with "...") shown as quotation preview.
// ─────────────────────────────────────────────────────────────────────────────

import type { Citation } from '../api/types';

interface CitationCardProps {
  citation: Citation;
}

export function CitationCard({ citation }: CitationCardProps) {
  const sourceLabel = citation.source_file
    ? citation.page_number !== null
      ? `${citation.source_file}, p. ${citation.page_number}`
      : citation.source_file
    : 'Document no longer available';

  return (
    <figure className="text-xs bg-gray-50 dark:bg-gray-800/70 border border-gray-200 dark:border-gray-700/80 rounded-lg p-3 space-y-1.5 transition-colors">
      <figcaption className="flex items-center gap-1.5 font-medium text-gray-700 dark:text-gray-300">
        <svg
          className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400 shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <span className="truncate" title={sourceLabel}>
          {sourceLabel}
        </span>
      </figcaption>

      {citation.text_snippet && (
        <blockquote className="text-gray-600 dark:text-gray-400 italic line-clamp-3 pl-2 border-l-2 border-gray-300 dark:border-gray-600">
          &ldquo;{citation.text_snippet}&rdquo;
        </blockquote>
      )}
    </figure>
  );
}

