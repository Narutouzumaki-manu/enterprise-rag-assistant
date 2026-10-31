import { describe, it, expect } from 'vitest';
import { parseSSEStream, type SSETermination } from '../api/sse';
import type { StreamEvent } from '../api/types';

// ─── Test helpers ─────────────────────────────────────────────────────────────

/**
 * Build a ReadableStream<Uint8Array> from an array of raw text chunks.
 * The stream closes after all chunks have been enqueued — simulating a
 * server that sends N network packets and then closes the connection.
 */
function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

/** Run parseSSEStream and collect both events and the termination reason. */
async function collect(
  chunks: string[],
  signal?: AbortSignal,
): Promise<{ events: StreamEvent[]; termination: SSETermination }> {
  const events: StreamEvent[] = [];
  const termination = await parseSSEStream(
    makeStream(chunks),
    (e) => events.push(e),
    signal,
  );
  return { events, termination };
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('parseSSEStream', () => {
  // ── Basic parsing ──────────────────────────────────────────────────────────

  it('parses a single status event delivered in one chunk', async () => {
    const { events, termination } = await collect([
      'event: status\ndata: {"step_type":"plan","content":"Planning the query..."}\n\n',
    ]);

    expect(termination).toBe('connection_lost'); // no done/error event
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: 'status',
      step_type: 'plan',
      content: 'Planning the query...',
    });
  });

  it('parses a token event', async () => {
    const { events } = await collect([
      'event: token\ndata: {"text":"Hello "}\n\n',
    ]);
    expect(events[0]).toMatchObject({ event: 'token', text: 'Hello ' });
  });

  it('parses a source event with all nullable fields present', async () => {
    const { events } = await collect([
      'event: source\ndata: {"chunk_id":"c1","document_id":"d1",' +
        '"source_file":"report.pdf","page_number":12,"text_snippet":"...excerpt..."}\n\n',
    ]);
    expect(events[0]).toMatchObject({
      event: 'source',
      chunk_id: 'c1',
      source_file: 'report.pdf',
      page_number: 12,
    });
  });

  // ── Split-chunk handling ───────────────────────────────────────────────────

  it('reassembles a block split mid-line across two chunks', async () => {
    const { events } = await collect([
      'event: status\n',
      'data: {"step_type":"retrieve","conte',
      'nt":"Retrieved 4 passages"}\n\n',
    ]);

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: 'status',
      step_type: 'retrieve',
      content: 'Retrieved 4 passages',
    });
  });

  it('reassembles a block split between event and data lines', async () => {
    const { events } = await collect([
      'event: token\n',
      'data: {"text":"word "}\n',
      '\n', // blank line arrives in a separate chunk
    ]);

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ event: 'token', text: 'word ' });
  });

  it('handles two complete blocks arriving in one chunk', async () => {
    const { events } = await collect([
      'event: token\ndata: {"text":"one "}\n\nevent: token\ndata: {"text":"two "}\n\n',
    ]);

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ text: 'one ' });
    expect(events[1]).toMatchObject({ text: 'two ' });
  });

  // ── Comment lines ─────────────────────────────────────────────────────────

  it('ignores SSE comment lines (: keep-alive) between blocks', async () => {
    const { events } = await collect([
      ': keep-alive\n\n',
      'event: token\ndata: {"text":"word "}\n\n',
      ': keep-alive\n\n',
    ]);

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ event: 'token', text: 'word ' });
  });

  it('ignores a block that contains only comment lines', async () => {
    const { events } = await collect([': comment-only\n\n']);
    expect(events).toHaveLength(0);
  });

  it('ignores a comment line that appears inside a real block', async () => {
    const { events } = await collect([
      'event: token\n: inline comment\ndata: {"text":"hi "}\n\n',
    ]);
    expect(events[0]).toMatchObject({ text: 'hi ' });
  });

  // ── Termination events ────────────────────────────────────────────────────

  it('returns "done" when the stream ends with a done event', async () => {
    const { termination, events } = await collect([
      'event: done\ndata: {"request_id":"r1","confidence":0.95,"latency_ms":4200}\n\n',
    ]);

    expect(termination).toBe('done');
    expect(events[0]).toMatchObject({ event: 'done', request_id: 'r1' });
  });

  it('returns "error" when the stream ends with an error event', async () => {
    const { termination, events } = await collect([
      'event: error\ndata: {"error":"Something went wrong","code":"INTERNAL_ERROR"}\n\n',
    ]);

    expect(termination).toBe('error');
    expect(events[0]).toMatchObject({ event: 'error', code: 'INTERNAL_ERROR' });
  });

  it('returns "connection_lost" when the stream closes without done or error', async () => {
    const { termination, events } = await collect([
      'event: status\ndata: {"step_type":"plan","content":"Planning..."}\n\n',
      // connection drops here — no done/error
    ]);

    expect(termination).toBe('connection_lost');
    // The status event was still delivered before the connection dropped
    expect(events).toHaveLength(1);
  });

  it('returns "connection_lost" on a completely empty stream', async () => {
    const { termination, events } = await collect([]);
    expect(termination).toBe('connection_lost');
    expect(events).toHaveLength(0);
  });

  // ── AbortSignal ──────────────────────────────────────────────────────────

  it('returns "aborted" immediately when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();

    const encoder = new TextEncoder();
    // An infinite stream that never closes on its own — simulates a slow server
    const neverEndingStream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.enqueue(
          encoder.encode(
            'event: status\ndata: {"step_type":"plan","content":"..."}\n\n',
          ),
        );
        // Intentionally never calls ctrl.close()
      },
    });

    const events: StreamEvent[] = [];
    const termination = await parseSSEStream(
      neverEndingStream,
      (e) => events.push(e),
      controller.signal,
    );

    expect(termination).toBe('aborted');
  });

  // ── Full sequence ──────────────────────────────────────────────────────────

  it('parses a realistic full stream sequence in order', async () => {
    const { events, termination } = await collect([
      'event: status\ndata: {"step_type":"plan","content":"Planning..."}\n\n',
      ': keep-alive\n\n',
      'event: status\ndata: {"step_type":"retrieve","content":"Retrieving 6 passages"}\n\n',
      'event: source\ndata: {"chunk_id":"c1","document_id":"d1","source_file":"a.pdf","page_number":3,"text_snippet":"...text..."}\n\n',
      ': keep-alive\n\n',
      'event: status\ndata: {"step_type":"synthesize","content":"Writing answer..."}\n\n',
      'event: status\ndata: {"step_type":"fact_check","content":"3 of 4 claims verified"}\n\n',
      'event: token\ndata: {"text":"The "}\n\n',
      'event: token\ndata: {"text":"answer "}\n\n',
      'event: token\ndata: {"text":"is 42."}\n\n',
      'event: verification\ndata: {"status":"verified","confidence":0.92}\n\n',
      'event: done\ndata: {"request_id":"req-1","confidence":0.92,"latency_ms":9800}\n\n',
    ]);

    expect(termination).toBe('done');
    // 4 status + 1 source + 3 token + 1 verification + 1 done = 10 (2 keep-alives ignored)
    expect(events.map((e) => e.event)).toEqual([
      'status', 'status', 'source', 'status', 'status',
      'token', 'token', 'token',
      'verification', 'done',
    ]);

    expect(events[0]).toMatchObject({ event: 'status', step_type: 'plan' });
    expect(events.find((e) => e.event === 'source')).toMatchObject({ chunk_id: 'c1' });

    const tokens = events.filter((e) => e.event === 'token');
    expect(tokens.map((t) => ('text' in t ? t.text : '')).join('')).toBe('The answer is 42.');

    expect(events.find((e) => e.event === 'verification')).toMatchObject({
      status: 'verified',
    });
    expect(events[events.length - 1]).toMatchObject({ event: 'done' });
  });
});
