// ─────────────────────────────────────────────────────────────────────────────
// UploadArea.tsx — Drag & drop upload area with per-file progress bars.
// Multiple files supported concurrently and independently.
// ─────────────────────────────────────────────────────────────────────────────

import React, { useState, useRef, useCallback } from 'react';
import { validateFile, uploadFileXHR } from '../api/upload';

interface FileUploadTask {
  id: string;
  file: File;
  progress: number;
  status: 'validating' | 'uploading' | 'success' | 'duplicate' | 'error';
  errorMessage: string | null;
}

interface UploadAreaProps {
  onUploadSuccess: () => void;
}

export function UploadArea({ onUploadSuccess }: UploadAreaProps) {
  const [tasks, setTasks] = useState<FileUploadTask[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const processFile = useCallback(
    async (file: File) => {
      const taskId = `${file.name}-${Date.now()}-${Math.random()}`;

      // 1. Client-side validation before touching network
      const validationError = validateFile(file);
      if (validationError) {
        setTasks((prev) => [
          ...prev,
          {
            id: taskId,
            file,
            progress: 0,
            status: 'error',
            errorMessage: validationError,
          },
        ]);
        return;
      }

      // 2. Add task in uploading state
      setTasks((prev) => [
        ...prev,
        {
          id: taskId,
          file,
          progress: 0,
          status: 'uploading',
          errorMessage: null,
        },
      ]);

      try {
        const result = await uploadFileXHR(file, (percent) => {
          setTasks((prev) =>
            prev.map((t) => (t.id === taskId ? { ...t, progress: percent } : t)),
          );
        });

        setTasks((prev) =>
          prev.map((t) =>
            t.id === taskId
              ? {
                  ...t,
                  progress: 100,
                  status: result.isDuplicate ? 'duplicate' : 'success',
                }
              : t,
          ),
        );

        onUploadSuccess();
      } catch (err) {
        const errorMsg =
          err instanceof Error
            ? err.message
            : 'Upload failed. Please check your connection and try again.';
        setTasks((prev) =>
          prev.map((t) =>
            t.id === taskId
              ? { ...t, status: 'error', errorMessage: errorMsg }
              : t,
          ),
        );
      }
    },
    [onUploadSuccess],
  );

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      Array.from(files).forEach((file) => {
        void processFile(file);
      });
    },
    [processFile],
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
      // Reset input so same file can be selected again if needed
      e.target.value = '';
    }
  };

  const removeTask = (taskId: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
  };

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        tabIndex={0}
        role="button"
        aria-label="Upload files by dragging and dropping or clicking to browse"
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
          isDragOver
            ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-950/20'
            : 'border-gray-300 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-600 bg-gray-50/50 dark:bg-gray-900/50'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.csv"
          onChange={handleInputChange}
          className="hidden"
          id="file-upload-input"
          aria-hidden="true"
        />

        <div className="flex flex-col items-center justify-center space-y-2">
          <svg
            className="w-10 h-10 text-gray-400 dark:text-gray-500"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <div className="text-sm text-gray-600 dark:text-gray-300">
            <span className="font-semibold text-blue-600 dark:text-blue-400">
              Click to choose files
            </span>{' '}
            or drag and drop them here
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            PDF, DOCX, and CSV up to 25 MB each
          </p>
        </div>
      </div>

      {/* Progress & Status list for current uploads */}
      {tasks.length > 0 && (
        <div className="space-y-2">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="bg-white dark:bg-gray-800 p-3 rounded-lg border border-gray-200 dark:border-gray-700 text-sm shadow-sm"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-gray-900 dark:text-white truncate max-w-sm">
                  {task.file.name}
                </span>
                <div className="flex items-center space-x-2">
                  {task.status === 'uploading' && (
                    <span className="text-xs text-blue-600 dark:text-blue-400">
                      {task.progress}%
                    </span>
                  )}
                  {task.status === 'success' && (
                    <span className="text-xs text-green-600 dark:text-green-400 font-medium">
                      ✓ Uploaded
                    </span>
                  )}
                  {task.status === 'duplicate' && (
                    <span className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                      ℹ️ Already uploaded
                    </span>
                  )}
                  {task.status === 'error' && (
                    <span className="text-xs text-red-600 dark:text-red-400 font-medium">
                      ✕ Failed
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => removeTask(task.id)}
                    aria-label={`Dismiss ${task.file.name}`}
                    className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 ml-2"
                  >
                    ✕
                  </button>
                </div>
              </div>

              {task.status === 'uploading' && (
                <div
                  className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden"
                  role="progressbar"
                  aria-valuenow={task.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`Uploading ${task.file.name}`}
                >
                  <div
                    className="bg-blue-600 h-1.5 rounded-full transition-all duration-150"
                    style={{ width: `${task.progress}%` }}
                  />
                </div>
              )}

              {task.status === 'error' && task.errorMessage && (
                <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                  {task.errorMessage}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

