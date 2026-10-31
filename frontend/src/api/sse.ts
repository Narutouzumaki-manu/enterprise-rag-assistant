// ─────────────────────────────────────────────────────────────────────────────
// sse.ts — Server-Sent Events parser for ReadableStream<Uint8Array>.
//
// The chat endpoint (POST /chat/stream) is a POST, so EventSource cannot be
// used.  We instead call fetch() with the Authorization header and read
// response.body as a ReadableStream, parsing the SSE text format ourselves.
//
// SSE format (RFC):
//   event: <name>\n
//   data: <json>\n
//   \n                ← blank line terminates one block/message
//   : keep-alive\n\n  ← comment line; ignore entire block
//
// Challenges handled here:
//   • Network chunks may split mid-line OR mid-block.
//   • Comment lines (starting with ":") must be silently ignored.
//   • Exactly one of "done" or "error" ends every successful stream.
//   • If the connection closes without either, we signal "connection_lost".
//   • An AbortSignal can cancel reading at any point.
// ─────────────────────────────────────────────────────────────────────────────

import type { StreamEvent } from './types';

// ─── Public types ─────────────────────────────────────────────────────────────

/** How the stream ended — used by useChatStream to decide what to show. */
export type SSETermination =
  | 'done'             // server sent the "done" event
  | 'error'            // server sent the "error" event
  | 'aborted'          // the user (or logout) cancelled via AbortSignal
  | 'connection_lost'; // connection dropped without a terminal event

// ─── Internal helpers ─────────────────────────────────────────────────────────

interface ParsedBlock {
  event?: string;
  /** All data lines joined by '\n' (multi-line data per SSE spec). */
  data?: string;
}

/**
 * Parse one complete SSE block (text between two blank lines).
 * Lines starting with ":" are SSE comments and are silently skipped.
 */
function extractFields(rawBlock: string): ParsedBlock {
  const result: ParsedBlock = {};
  for (const line of rawBlock.split('\n')) {
    if (line.startsWith(':')) continue; // SSE comment — ignore
    if (line.startsWith('event:')) {
      result.event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      const value = line.slice(5).trim();
      result.data =
        result.data !== undefined ? `${result.data}\n${value}` : value;
    }
  }
  return result;
}

/** Convert a parsed block to a typed StreamEvent, or null if it can't be parsed. */
function toStreamEvent(block: ParsedBlock): StreamEvent | null {
  if (!block.event || block.data === undefined) return null;
  try {
    const payload = JSON.parse(block.data) as Record<string, unknown>;
    // Spread the payload and attach the discriminant "event" field.
    return { event: block.event, ...payload } as StreamEvent;
  } catch {
    // Malformed JSON — skip this block
    return null;
  }
}

// ─── Main export ──────────────────────────────────────────────────────────────

/**
 * Reads an SSE stream from a POST response body and calls onEvent for each
 * valid event.  Returns a SSETermination value when the stream ends.
 *
 * @param body     response.body from the fetch call
 * @param onEvent  called synchronously for every parsed StreamEvent
 * @param signal   optional AbortSignal; aborting sets termination to 'aborted'
 */
export async function parseSSEStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<SSETermination> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let termination: SSETermination = 'connection_lost';

  /**
   * Split the buffer on blank lines, dispatch complete blocks, and retain
   * any trailing incomplete block in the buffer.
   */
  const flushBuffer = (): void => {
    // Normalise \r\n and lone \r to \n for robustness across platforms
    const normalised = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const parts = normalised.split('\n\n');
    // The last part may be incomplete (no closing blank line yet)
    buffer = parts.pop() ?? '';

    for (const part of parts) {
      if (!part.trim()) continue; // blank block (e.g. a comment-only block)
      const block = extractFields(part);
      const event = toStreamEvent(block);
      if (!event) continue;

      // Record terminal events before calling onEvent so the caller sees the
      // correct termination even if it throws.
      if (event.event === 'done') termination = 'done';
      else if (event.event === 'error') termination = 'error';

      onEvent(event);
    }
  };

  try {
    while (true) {
      // Check abort before each read so we never block on a cancelled fetch.
      if (signal?.aborted) {
        termination = 'aborted';
        break;
      }

      let done: boolean;
      let value: Uint8Array | undefined;

      try {
        ({ done, value } = await reader.read());
      } catch {
        // reader.read() throws a DOMException('AbortError') when the fetch is
        // aborted mid-stream.
        if (signal?.aborted) {
          termination = 'aborted';
        }
        break;
      }

      if (done) break;

      if (value) {
        // stream: true tells TextDecoder to handle multi-byte chars split
        // across chunks without corrupting them.
        buffer += decoder.decode(value, { stream: true });
        flushBuffer();
      }
    }

    // Edge case: stream ended but the last block had no trailing blank line.
    if (buffer.trim()) {
      buffer += '\n\n';
      flushBuffer();
    }
  } finally {
    // Always release the reader lock, even if we threw.
    try {
      reader.releaseLock();
    } catch {
      // Already released or the stream was cancelled — nothing to do.
    }
  }

  return termination;
}

