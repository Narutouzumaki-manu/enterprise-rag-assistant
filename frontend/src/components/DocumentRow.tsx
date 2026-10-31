// ─────────────────────────────────────────────────────────────────────────────
// DocumentRow.tsx — Table row / card rendering a single document.
// Shows human-readable status, formatted date, and delete with confirmation
// only when uploaded_by_me is true.
// ─────────────────────────────────────────────────────────────────────────────

import  { useState } from 'react';
import type { Document, DocumentStatus } from '../api/types';

interface DocumentRowProps {
  doc: Document;
  onDelete: (docId: string) => Promise<void>;
  isDeleting: boolean;
  deleteError: string | null;
}

export function getStatusDisplay(
  status: DocumentStatus,
  errorMessage: string | null,
): { text: string; badgeClass: string; icon: string } {
  switch (status) {
    case 'queued':
      return {
        text: 'Waiting to be processed...',
        badgeClass:
          'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300 border-gray-300 dark:border-gray-700',
        icon: '⏳',
      };
    case 'parsing':
      return {
        text: 'Reading document...',
        badgeClass:
          'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border-blue-200 dark:border-blue-800',
        icon: '📄',
      };
    case 'indexing':
      return {
        text: 'Making it searchable...',
        badgeClass:
          'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300 border-purple-200 dark:border-purple-800',
        icon: '🔍',
      };
    case 'success':
      return {
        text: 'Ready',
        badgeClass:
          'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 border-green-200 dark:border-green-800',
        icon: '✓',
      };
    case 'partial':
      return {
        text: 'Partly processed: some pages could not be read',
        badgeClass:
          'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-800',
        icon: '⚠️',
      };
    case 'duplicate':
      return {
        text: 'This document was already uploaded',
        badgeClass:
          'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 border-blue-200 dark:border-blue-800',
        icon: 'ℹ️',
      };
    case 'failed':
      return {
        text: errorMessage || 'Processing failed.',
        badgeClass:
          'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 border-red-200 dark:border-red-800',
        icon: '✕',
      };
  }
}

export function DocumentRow({
  doc,
  onDelete,
  isDeleting,
  deleteError,
}: DocumentRowProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const statusDisplay = getStatusDisplay(doc.status, doc.error_message);

  const formattedDate = new Date(doc.created_at).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  const handleDelete = async () => {
    try {
      await onDelete(doc.document_id);
      setShowConfirm(false);
    } catch {
      // Keep confirm dialog open or let deleteError show
    }
  };

  return (
    <tr className="border-b border-gray-200 dark:border-gray-800 hover:bg-gray-50/50 dark:hover:bg-gray-800/50 transition-colors">
      <td className="px-6 py-4 whitespace-nowrap">
        <div className="flex items-center space-x-2">
          <span className="text-gray-400 dark:text-gray-500 font-mono text-xs uppercase px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
            {doc.source_type}
          </span>
          <span className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-xs md:max-w-md">
            {doc.filename}
          </span>
        </div>
      </td>

      <td className="px-6 py-4">
        <span
          className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${statusDisplay.badgeClass}`}
          role="status"
        >
          <span className="mr-1.5" aria-hidden="true">
            {statusDisplay.icon}
          </span>
          <span>{statusDisplay.text}</span>
        </span>
      </td>

      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
        <time dateTime={doc.created_at}>{formattedDate}</time>
      </td>

      <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
        {doc.uploaded_by_me && (
          <div className="relative inline-block text-left">
            {!showConfirm ? (
              <button
                type="button"
                onClick={() => setShowConfirm(true)}
                disabled={isDeleting}
                aria-label={`Delete ${doc.filename}`}
                className="text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 font-medium text-sm focus:outline-none focus:ring-2 focus:ring-red-500 rounded px-2 py-1 disabled:opacity-50"
              >
                Delete
              </button>
            ) : (
              <div
                role="dialog"
                aria-label={`Confirm deletion of ${doc.filename}`}
                className="flex items-center space-x-2 bg-white dark:bg-gray-800 p-2 rounded-lg shadow-lg border border-gray-300 dark:border-gray-700 z-10"
              >
                <span className="text-xs text-gray-700 dark:text-gray-300">
                  Delete?
                </span>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={isDeleting}
                  className="px-2 py-1 text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50"
                >
                  {isDeleting ? 'Deleting...' : 'Yes, delete'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowConfirm(false)}
                  disabled={isDeleting}
                  className="px-2 py-1 text-xs font-semibold text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded focus:outline-none focus:ring-2 focus:ring-gray-400"
                >
                  Cancel
                </button>
                {deleteError && (
                  <span className="text-xs text-red-600 dark:text-red-400 ml-2">
                    {deleteError}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

