// ─────────────────────────────────────────────────────────────────────────────
// Documents.tsx — Document management page: upload, polling list, delete.
// ─────────────────────────────────────────────────────────────────────────────

import  { useState, useEffect } from 'react';
import { NavBar } from '../components/NavBar';
import { UploadArea } from '../components/UploadArea';
import { DocumentRow } from '../components/DocumentRow';
import { useDocuments } from '../hooks/useDocuments';

export function Documents() {
  const {
    documents,
    isLoading,
    isError,
    error,
    refetch,
    deleteDocument,
    isDeleting,
    deleteError,
  } = useDocuments();

  // Retry-after countdown if 429 / 503 error occurs
  const [countdown, setCountdown] = useState<number | null>(null);

  useEffect(() => {
    if (error?.retryAfter && error.retryAfter > 0) {
      setCountdown(error.retryAfter);
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
  }, [error]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <NavBar />

      <main className="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8 space-y-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
            Documents
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Upload files for the assistant to analyze and cite in its answers.
          </p>
        </div>

        {/* Upload section */}
        <section aria-labelledby="upload-heading">
          <h2 id="upload-heading" className="sr-only">
            Upload Documents
          </h2>
          <UploadArea onUploadSuccess={() => void refetch()} />
        </section>

        {/* Temporary error with countdown & retry button (429/503) */}
        {isError && error && (
          <div
            role="alert"
            className="p-4 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
          >
            <div>
              <p className="font-semibold text-sm">{error.error}</p>
              {error.status === 429 || error.status === 503 ? (
                <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
                  Please try again in a moment.
                  {countdown !== null ? ` (Available in ${countdown}s)` : ''}
                </p>
              ) : null}
              {error.requestId && (
                <p className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-1">
                  Request ID: {error.requestId}
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={() => void refetch()}
              disabled={countdown !== null}
              className="px-3 py-1.5 text-xs font-semibold rounded-md bg-amber-600 hover:bg-amber-700 text-white focus:outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {countdown !== null ? `Wait ${countdown}s` : 'Try again'}
            </button>
          </div>
        )}

        {/* Documents list */}
        <section aria-labelledby="documents-heading" className="space-y-4">
          <div className="flex items-center justify-between">
            <h2
              id="documents-heading"
              className="text-lg font-semibold text-gray-900 dark:text-white"
            >
              Uploaded Documents ({documents.length})
            </h2>
          </div>

          {isLoading ? (
            <div className="py-12 text-center text-sm text-gray-500 dark:text-gray-400">
              Loading documents...
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-12 px-4 rounded-xl border border-dashed border-gray-300 dark:border-gray-800 bg-white dark:bg-gray-900">
              <svg
                className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                No documents uploaded yet
              </h3>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Upload a PDF, DOCX, or CSV file above to get started.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto shadow ring-1 ring-black ring-opacity-5 rounded-lg bg-white dark:bg-gray-900">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800">
                <thead className="bg-gray-50 dark:bg-gray-800/60">
                  <tr>
                    <th
                      scope="col"
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                    >
                      Document
                    </th>
                    <th
                      scope="col"
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                    >
                      Status
                    </th>
                    <th
                      scope="col"
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                    >
                      Uploaded
                    </th>
                    <th scope="col" className="relative px-6 py-3">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-800">
                  {documents.map((doc) => (
                    <DocumentRow
                      key={doc.document_id}
                      doc={doc}
                      onDelete={deleteDocument}
                      isDeleting={isDeleting}
                      deleteError={deleteError}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

