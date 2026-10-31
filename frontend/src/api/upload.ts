// ─────────────────────────────────────────────────────────────────────────────
// upload.ts — client-side file validation + XHR upload helper.
//
// Extracted to a separate module so unit tests can validate without mocking XHR,
// and integration tests can mock uploadFileXHR cleanly.
// ─────────────────────────────────────────────────────────────────────────────

import { getToken } from './tokenStore';
import type { UploadResponse } from './types';

// ─── Constants ────────────────────────────────────────────────────────────────

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // 25 MB

/** File extensions accepted by POST /documents/upload. */
export const ALLOWED_EXTENSIONS = new Set(['.pdf', '.docx', '.csv']);

// ─── Validation ───────────────────────────────────────────────────────────────

function fileExtension(filename: string): string {
  const idx = filename.lastIndexOf('.');
  return idx >= 0 ? filename.slice(idx).toLowerCase() : '';
}

/**
 * Validate a File before starting the upload.
 * Returns a human-readable error string, or null if the file passes.
 * Called before any XHR is opened, so a failed validation never touches the network.
 */
export function validateFile(file: File): string | null {
  const ext = fileExtension(file.name);
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return (
      `"${file.name}" is not a supported type. ` +
      'Only PDF, DOCX, and CSV files can be uploaded.'
    );
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    return `"${file.name}" is ${mb} MB. Files must be 25 MB or smaller.`;
  }
  return null;
}

// ─── XHR Upload ───────────────────────────────────────────────────────────────

export interface UploadResult {
  response: UploadResponse;
  /** true when the server returns 200 with status "duplicate" */
  isDuplicate: boolean;
}

/**
 * Upload a single file via XMLHttpRequest so real upload progress is available.
 * fetch() does not expose upload progress on the browser side.
 *
 * Resolves on 200 (duplicate) or 202 (queued).
 * Rejects with an Error whose .message is the server's "error" text, or a
 * human-readable network-failure message.
 */
export function uploadFileXHR(
  file: File,
  onProgress: (percent: number) => void,
): Promise<UploadResult> {
  return new Promise<UploadResult>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    // The backend expects the field name "file"
    formData.append('file', file);

    // Real upload progress (fired every ~50 ms while bytes are in flight)
    xhr.upload.addEventListener('progress', (e: ProgressEvent) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status === 202 || xhr.status === 200) {
        try {
          const body = JSON.parse(xhr.responseText) as UploadResponse;
          resolve({ response: body, isDuplicate: body.status === 'duplicate' });
        } catch {
          reject(new Error('Unexpected response from server.'));
        }
        return;
      }
      // Non-2xx — parse the standard error body
      try {
        const body = JSON.parse(xhr.responseText) as { error: string };
        reject(new Error(body.error));
      } catch {
        reject(new Error(`Upload failed (HTTP ${xhr.status}).`));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Could not reach the server. Please check your connection.'));
    });

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload was cancelled.'));
    });

    xhr.open('POST', '/documents/upload');
    const token = getToken();
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }
    xhr.send(formData);
  });
}

