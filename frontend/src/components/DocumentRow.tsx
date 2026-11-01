// ─────────────────────────────────────────────────────────────────────────────
// DocumentRow.tsx — Table row / card rendering a single document.
// Shows human-readable status, formatted date, and delete with confirmation
// only when uploaded_by_me is true.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect } from 'react';
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
  const deleteBtnRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const formattedDate = new Date(doc.created_at).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  const prevShowConfirmRef = useRef(showConfirm);
  useEffect(() => {
    if (prevShowConfirmRef.current && !showConfirm) {
      deleteBtnRef.current?.focus();
    }
    prevShowConfirmRef.current = showConfirm;
  }, [showConfirm]);

  // Focus trap and Escape handling for delete dialog
  useEffect(() => {
    if (!showConfirm) return;

    // Focus the first button inside dialog on open
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>('button, [href], input, [tabindex="0"]');
    if (focusable && focusable.length > 0) {
      focusable[0].focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowConfirm(false);
        return;
      }

      if (e.key === 'Tab') {
        if (!dialogRef.current) return;
        const buttons = dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled])');
        if (buttons.length === 0) return;

        const first = buttons[0];
        const last = buttons[buttons.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [showConfirm]);

  const handleDelete = async () => {
    try {
      await onDelete(doc.document_id);
      setShowConfirm(false);
    } catch {
      // Keep confirm dialog open or let deleteError show
    }
  };

  const handleCancel = () => {
    setShowConfirm(false);
  };

  return (
    <tr className="border-b border-gray-200 dark:border-gray-800 hover:bg-gray-50/50 dark:hover:bg-gray-800/50 transition-colors">
      <td className="px-4 sm:px-6 py-4 whitespace-nowrap">
        <div className="flex items-center space-x-2">
          <span className="text-gray-600 dark:text-gray-400 font-mono text-xs uppercase px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
            {doc.source_type}
          </span>
          <span className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-xs md:max-w-md">
            {doc.filename}
          </span>
        </div>
      </td>

      <td className="px-4 sm:px-6 py-4">
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

      <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
        <time dateTime={doc.created_at}>{formattedDate}</time>
      </td>

      <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
        {doc.uploaded_by_me && (
          <div className="relative inline-block text-left">
            {!showConfirm ? (
              <button
                ref={deleteBtnRef}
                type="button"
                onClick={() => setShowConfirm(true)}
                disabled={isDeleting}
                aria-label={`Delete ${doc.filename}`}
                className="text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 font-medium text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 rounded px-2.5 py-1.5 min-h-[40px] inline-flex items-center disabled:opacity-50"
              >
                Delete
              </button>
            ) : (
              <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={`delete-title-${doc.document_id}`}
                aria-describedby={`delete-desc-${doc.document_id}`}
                className="flex items-center flex-wrap gap-2 bg-white dark:bg-gray-800 p-2.5 rounded-lg shadow-lg border border-gray-300 dark:border-gray-700 z-10"
              >
                <span id={`delete-title-${doc.document_id}`} className="text-xs font-medium text-gray-700 dark:text-gray-300">
                  Delete?
                </span>
                <span id={`delete-desc-${doc.document_id}`} className="sr-only">
                  Confirm deletion of {doc.filename}. This action cannot be undone.
                </span>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={isDeleting}
                  className="px-3 py-1.5 min-h-[40px] inline-flex items-center text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50"
                >
                  {isDeleting ? 'Deleting...' : 'Yes, delete'}
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={isDeleting}
                  className="px-3 py-1.5 min-h-[40px] inline-flex items-center text-xs font-semibold text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
                >
                  Cancel
                </button>
                {deleteError && (
                  <span className="text-xs text-red-600 dark:text-red-400 ml-1">
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

