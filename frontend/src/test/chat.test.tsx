import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { type ReactElement } from 'react';
import { AuthProvider } from '../hooks/useAuth';
import { TrustBadge } from '../components/TrustBadge';
import { AnswerCard } from '../components/AnswerCard';
import { InlineErrorNotice } from '../components/ErrorState';
import { Chat } from '../pages/Chat';
import { EXAMPLE_QUESTIONS, CONNECTION_LOST_MESSAGE } from '../constants';
import * as clientModule from '../api/client';
import type { SessionDetail, SessionSummary, Document } from '../api/types';

// ─── Test fixtures ────────────────────────────────────────────────────────────

const mockDocuments: Document[] = [
  {
    document_id: 'doc-1',
    filename: 'annual_report.pdf',
    status: 'success',
    error_message: null,
    source_type: 'pdf',
    created_at: '2026-10-31T00:00:00Z',
    uploaded_by_me: true,
  },
];

const mockSessionSummary: SessionSummary = {
  session_id: 'sess-100',
  title: 'Financial Review',
  created_at: '2026-10-31T00:00:00Z',
  updated_at: '2026-10-31T00:00:00Z',
};

const mockSessionDetail: SessionDetail = {
  ...mockSessionSummary,
  messages: [
    {
      message_id: 'msg-user-1',
      role: 'user',
      content: 'What was the Q3 revenue?',
      created_at: '2026-10-31T00:00:00Z',
      verification_status: null,
      confidence: null,
      latency_ms: null,
      citations: [],
      trace: [],
    },
    {
      message_id: 'msg-asst-1',
      role: 'assistant',
      content: 'The Q3 revenue was $4.2B.',
      created_at: '2026-10-31T00:01:00Z',
      verification_status: 'verified',
      confidence: 0.98,
      latency_ms: 1200,
      citations: [
        {
          chunk_id: 'chk-1',
          document_id: 'doc-1',
          source_file: 'annual_report.pdf',
          page_number: 14,
          text_snippet: '...Q3 revenue totaled $4.2B...',
        },
      ],
      trace: [
        {
          step_type: 'retrieve',
          content: 'Retrieved 3 passages',
          metadata: {},
        },
      ],
    },
  ],
};

// ─── Render helper ────────────────────────────────────────────────────────────

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/chat" element={ui} />
            <Route path="/chat/:sessionId" element={ui} />
            <Route path="*" element={ui} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('1. Trust Badge Rendering & Rules', () => {
  it('renders "verified" badge with icon, green style, and "Found in your documents"', () => {
    render(<TrustBadge status="verified" />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveTextContent('Found in your documents');
    expect(badge.className).toContain('text-emerald-800');
    expect(badge.innerHTML).not.toContain('confidence');
    expect(badge.innerHTML).not.toContain('correct');
    expect(badge.innerHTML).not.toContain('accurate');
    expect(badge.innerHTML).not.toContain('guaranteed');
  });

  it('renders "partially_verified" badge with caution icon, amber style, and contract text', () => {
    render(<TrustBadge status="partially_verified" />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveTextContent('Some parts could not be fully verified');
    expect(badge.className).toContain('text-amber-800');
  });

  it('renders "unverified" badge with warning icon, strong rose/red style', () => {
    render(<TrustBadge status="unverified" />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveTextContent('Unverified in documents');
    expect(badge.className).toContain('text-rose-800');
  });
});

describe('2. AnswerCard & Absence of Confidence', () => {
  it('never renders confidence percentage or number in the DOM', () => {
    const { container } = render(
      <AnswerCard
        content="Revenue is $5M."
        verificationStatus="verified"
        citations={[]}
        messageId="msg-1"
        isLive={false}
      />,
    );

    // Confidence must never appear
    expect(container.textContent).not.toContain('0.98');
    expect(container.textContent).not.toContain('98%');
    expect(container.textContent).not.toContain('confidence');
    expect(container.textContent).not.toContain('correct');
  });

  it('renders calm honest refusal without error styling', () => {
    render(
      <AnswerCard
        content="I don't have sufficient evidence in the provided documents."
        verificationStatus="unverified"
        citations={[]}
        messageId="msg-refusal"
      />,
    );

    expect(
      screen.getByText("I don't have sufficient evidence in the provided documents."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/service unavailable/i)).not.toBeInTheDocument();
  });

  it('renders "Try again" button for retriable refusal', () => {
    const onRetry = vi.fn();
    render(
      <AnswerCard
        content="I couldn't retrieve the document right now. Please try again."
        verificationStatus="unverified"
        citations={[]}
        messageId="msg-try-again"
        onRetryQuestion={onRetry}
      />,
    );

    const tryAgainBtn = screen.getByRole('button', { name: /try again/i });
    expect(tryAgainBtn).toBeInTheDocument();
    tryAgainBtn.click();
    expect(onRetry).toHaveBeenCalled();
  });
});

describe('3. 429 Countdown Notice', () => {
  it('shows countdown timer and disables button until countdown finishes', () => {
    vi.useFakeTimers();
    const onRetry = vi.fn();

    render(
      <InlineErrorNotice
        error="Too many requests"
        retryAfterSeconds={5}
        onRetry={onRetry}
      />,
    );

    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent('Wait 5s');
    expect(screen.getByText(/Please wait 5s before trying again/)).toBeInTheDocument();

    // Advance 3 seconds
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(btn).toHaveTextContent('Wait 2s');
    expect(btn).toBeDisabled();

    // Advance remaining 2 seconds
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(btn).not.toBeDisabled();
    expect(btn).toHaveTextContent('Try again');

    act(() => {
      btn.click();
    });
    expect(onRetry).toHaveBeenCalled();

    vi.useRealTimers();
  });
});

describe('4. Example Questions & Chat Interactions', () => {
  beforeEach(() => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('clicking an example question fills input and does NOT send request', async () => {
    // Empty session detail with 0 messages to show example questions
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({
          data: { ...mockSessionSummary, messages: [] },
          requestId: 'req-2',
        });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    renderWithProviders(<Chat />);

    // Wait for example questions to render
    await waitFor(() => {
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    expect(input.value).toBe('');

    // Click first example
    await user.click(screen.getByText(EXAMPLE_QUESTIONS[0]));

    // Input must be populated with the example
    expect(input.value).toBe(EXAMPLE_QUESTIONS[0]);

    // Crucial rule: It must NEVER send automatically
    expect(fetchSpy).not.toHaveBeenCalledWith(
      '/chat/stream',
      expect.anything(),
    );
  });
});

describe('5. Pre-stream 503 AGENT_BUSY keeps user question', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('displays inline error and preserves user question in input', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    // Mock createSession (apiPost /sessions) so we get a sessionId without a real network call
    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: mockSessionSummary,
      requestId: 'req-sess',
    });

    // Mock fetch for /chat/stream returning 503 AGENT_BUSY JSON
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'The service is busy. Please try again shortly.',
          code: 'AGENT_BUSY',
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    window.history.pushState({}, '', '/chat');
    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for documents to load: once hasDocuments=true, example questions appear
    await waitFor(() =>
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument(),
    );

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    await user.type(input, 'What are the risks?');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Wait for inline error
    await waitFor(() => {
      expect(
        screen.getByText('The service is busy. Please try again shortly.'),
      ).toBeInTheDocument();
    });

    // Question must be preserved in input box
    expect(input.value).toBe('What are the risks?');
  });
});

describe('6. Stream Termination without done/error', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('displays CONNECTION_LOST_MESSAGE when stream closes prematurely', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    // Mock createSession (apiPost /sessions) so we get a sessionId without a real network call
    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: mockSessionSummary,
      requestId: 'req-sess',
    });

    // Empty stream: closes immediately without a done or error event
    const emptyStream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.close();
      },
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(emptyStream, { status: 200 }),
    );

    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for documents to load
    await waitFor(() =>
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument(),
    );

    const input = screen.getByLabelText('Ask a question');
    await user.type(input, 'Tell me something');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByText(CONNECTION_LOST_MESSAGE)).toBeInTheDocument();
    });
  });
});

describe('7. Conversation Switching During a Stream', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("start a stream in session A, switch to B, send a question in B: B's live answer contains none of A's tokens or steps", async () => {
    const sessionA: SessionSummary = {
      session_id: 'sess-A',
      title: 'Conversation A',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T02:00:00Z',
    };
    const sessionB: SessionSummary = {
      session_id: 'sess-B',
      title: 'Conversation B',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T01:00:00Z',
    };

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url === '/sessions/sess-A') {
        return Promise.resolve({
          data: { ...sessionA, messages: [] },
          requestId: 'req-2',
        });
      }
      if (url === '/sessions/sess-B') {
        return Promise.resolve({
          data: { ...sessionB, messages: [] },
          requestId: 'req-3',
        });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [sessionA, sessionB], requestId: 'req-4' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    let controllerA: ReadableStreamDefaultController<Uint8Array>;
    const streamA = new ReadableStream<Uint8Array>({
      start(c) {
        controllerA = c;
        c.enqueue(
          new TextEncoder().encode(
            'event: status\ndata: {"step_type":"plan","content":"Step from A"}\n\nevent: token\ndata: {"text":"Answer token from A"}\n\n',
          ),
        );
      },
    });

    const streamB = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(
          new TextEncoder().encode(
            'event: status\ndata: {"step_type":"plan","content":"Step from B"}\n\nevent: token\ndata: {"text":"Answer token from B"}\n\n',
          ),
        );
      },
    });

    let fetchCallCount = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (typeof input === 'string' && input.includes('/chat/stream')) {
        fetchCallCount++;
        if (fetchCallCount === 1) {
          return Promise.resolve(new Response(streamA, { status: 200 }));
        }
        return Promise.resolve(new Response(streamB, { status: 200 }));
      }
      return Promise.reject(new Error(`Unhandled fetch ${String(input)}`));
    });

    window.history.pushState({}, '', '/chat/sess-A');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for documents to load
    await waitFor(() =>
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument(),
    );

    // Send question in session A
    const input = screen.getByLabelText('Ask a question');
    await user.type(input, 'Question for A');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Stream A emits initial tokens and steps from start()

    await waitFor(() => {
      expect(screen.getByText('Step from A')).toBeInTheDocument();
      expect(screen.getByText('Answer token from A')).toBeInTheDocument();
    });

    // Switch to Conversation B via sidebar
    const convBBtn = screen.getByRole('button', { name: /conversation b/i });
    await user.click(convBBtn);

    // In session B, send a question
    const inputB = screen.getByLabelText('Ask a question');
    await user.type(inputB, 'Question for B');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Stream B emits initial tokens and steps from start()

    // A late token from conversation A arrives now
    act(() => {
      try {
        controllerA.enqueue(
          new TextEncoder().encode('event: token\ndata: {"text":" Late token from A"}\n\n'),
        );
      } catch {
        // controller might already be closed/errored by abort
      }
    });

    await waitFor(() => {
      expect(screen.getByText('Step from B')).toBeInTheDocument();
      expect(screen.getByText('Answer token from B')).toBeInTheDocument();
    });

    // Verify session B contains none of A's tokens or steps
    expect(screen.queryByText('Step from A')).not.toBeInTheDocument();
    expect(screen.queryByText(/Answer token from A/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Late token from A/)).not.toBeInTheDocument();
  });

  it('first question in a new conversation (no sessionId, then the URL gets the new id) keeps its live steps', async () => {
    const newSessionSummary: SessionSummary = {
      session_id: 'sess-new-created',
      title: 'New conversation',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
    };

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url === '/sessions/sess-new-created') {
        return Promise.resolve({
          data: { ...newSessionSummary, messages: [] },
          requestId: 'req-2',
        });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [newSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: newSessionSummary,
      requestId: 'req-create',
    });

    let streamController: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        streamController = c;
      },
    });

    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (typeof input === 'string' && input.includes('/chat/stream')) {
        return Promise.resolve(new Response(stream, { status: 200 }));
      }
      return Promise.reject(new Error(`Unhandled fetch ${String(input)}`));
    });

    // Start at /chat without any sessionId in URL
    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for documents to load
    await waitFor(() =>
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument(),
    );

    const input = screen.getByLabelText('Ask a question');
    await user.type(input, 'First question in brand new conversation');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Stream status step arrives
    act(() => {
      streamController.enqueue(
        new TextEncoder().encode(
          'event: status\ndata: {"step_type":"retrieve","content":"Searching knowledge base for first question"}\n\n',
        ),
      );
    });

    // Verify live steps are retained and rendered even as the URL transitions to /chat/sess-new-created
    await waitFor(() => {
      expect(
        screen.getByText('Searching knowledge base for first question'),
      ).toBeInTheDocument();
    });

    expect(window.location.pathname).toBe('/chat/sess-new-created');
  });
});

describe('8. Non-existent or Invalid Session ID Redirection', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('redirects to /chat when session loading returns 422 (e.g. non-UUID path)', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        const error = new clientModule.ApiRequestError({
          error: 'Invalid request. session_id: Input should be a valid UUID',
          code: 'VALIDATION_ERROR',
          status: 422,
          requestId: 'req-err-422',
          retryAfter: null,
        });
        return Promise.reject(error);
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat/does-not-exist');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(window.location.pathname).toBe('/chat');
    });
  });

  it('redirects to /chat when session loading returns 404 (session not found)', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        const error = new clientModule.ApiRequestError({
          error: 'Session not found.',
          code: 'NOT_FOUND',
          status: 404,
          requestId: 'req-err-404',
          retryAfter: null,
        });
        return Promise.reject(error);
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat/00000000-0000-0000-0000-000000000000');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(window.location.pathname).toBe('/chat');
    });
  });
});

describe('9. Network Error / Backend Down Handling', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('displays "Connection lost. Please check your connection and try again." with "Retry" button on network failure', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: mockSessionSummary,
      requestId: 'req-sess-net',
    });

    // Mock fetch to simulate network error / connection refused (no HTTP response)
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(
      new TypeError('Failed to fetch'),
    );

    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for documents to load so starter questions appear
    await waitFor(() => {
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    await user.type(input, 'What is the quarterly growth?');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Verify inline error notice and Retry button
    await waitFor(() => {
      expect(
        screen.getByText(CONNECTION_LOST_MESSAGE),
      ).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    expect(retryBtn).toBeInTheDocument();

    // Verify question is preserved in input box
    expect(input.value).toBe('What is the quarterly growth?');

    // Verify no full-page Service Unavailable or blank screen
    expect(
      screen.queryByText('Service Temporarily Unavailable'),
    ).not.toBeInTheDocument();

    // Mock fetch for successful retry
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(ctrl) {
        ctrl.enqueue(
          encoder.encode(
            'event: token\ndata: {"text":"Quarterly growth was 15%."}\n\nevent: done\ndata: {}\n\n',
          ),
        );
        ctrl.close();
      },
    });

    fetchSpy.mockResolvedValueOnce(
      new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );

    // Click Retry
    await user.click(retryBtn);

    // Verify stream was retried with the same query
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/chat/stream',
        expect.objectContaining({
          body: JSON.stringify({
            session_id: 'sess-100',
            query: 'What is the quarterly growth?',
          }),
        }),
      );
    });
  });
});

describe('10. Query Validation & Non-Redirection on 422/Validation Errors', () => {
  beforeEach(() => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/sess-valid')) {
        return Promise.resolve({
          data: { ...mockSessionDetail, session_id: 'sess-valid' },
          requestId: 'req-sess-valid',
        });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({
          data: [{ ...mockSessionSummary, session_id: 'sess-valid' }],
          requestId: 'req-sessions',
        });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('blank query shows inline validation message under input and is NOT redirected to /chat', async () => {
    window.history.pushState({}, '', '/chat/sess-valid');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const form = screen.getByLabelText('Ask a question').closest('form')!;
    // Submit blank form
    act(() => {
      form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    });

    // Inline validation error message shown under input
    await waitFor(() => {
      expect(screen.getByText('Please enter a question.')).toBeInTheDocument();
    });

    // Confirms redirect applies only to loading conversation, NOT query validation
    expect(window.location.pathname).toBe('/chat/sess-valid');
  });

  it('2001-character query shows inline validation message under input and is NOT redirected to /chat', async () => {
    window.history.pushState({}, '', '/chat/sess-valid');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    const form = input.closest('form')!;

    // Directly set 2001 characters on the input (bypassing input element's HTML maxLength constraint)
    act(() => {
      input.maxLength = 5000;
      fireEvent.change(input, { target: { value: 'a'.repeat(2001) } });
    });

    act(() => {
      fireEvent.submit(form);
    });

    // Inline validation error message shown under input
    await waitFor(() => {
      expect(
        screen.getByText('Questions must be 2000 characters or fewer.'),
      ).toBeInTheDocument();
    });

    // Confirms redirect applies only to loading conversation, NOT query validation
    expect(window.location.pathname).toBe('/chat/sess-valid');
  });

  it('server 422 from POST /chat/stream shows inline error and is NOT redirected to /chat', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'Query validation failed on server.',
          code: 'VALIDATION_ERROR',
        }),
        {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    window.history.pushState({}, '', '/chat/sess-valid');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question');
    await user.type(input, 'Valid query length');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Inline error notice shown
    await waitFor(() => {
      expect(
        screen.getByText('Query validation failed on server.'),
      ).toBeInTheDocument();
    });

    // Confirms redirect applies only to loading conversation, NOT query validation
    expect(window.location.pathname).toBe('/chat/sess-valid');
  });
});

describe('11. Chat.tsx Second-Round Fixes', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('1. "Try again" on a SAVED assistant message resends the immediately preceding user message', async () => {
    const sessionWithSavedError: SessionDetail = {
      session_id: 'sess-saved-retry',
      title: 'Session to Retry',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
      messages: [
        {
          message_id: 'msg-u1',
          role: 'user',
          content: 'Q1',
          created_at: '2026-10-31T00:00:00Z',
          verification_status: null,
          confidence: null,
          latency_ms: null,
          citations: [],
          trace: [],
        },
        {
          message_id: 'msg-a1',
          role: 'assistant',
          content: "I couldn't write an answer right now. Please try again.",
          created_at: '2026-10-31T00:01:00Z',
          verification_status: 'unverified',
          confidence: 0.1,
          latency_ms: 500,
          citations: [],
          trace: [],
        },
      ],
    };

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/sess-saved-retry')) {
        return Promise.resolve({ data: sessionWithSavedError, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(ctrl) {
            ctrl.close();
          },
        }),
        { status: 200 },
      ),
    );

    window.history.pushState({}, '', '/chat/sess-saved-retry');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Wait for the assistant message and its Try again button
    await waitFor(() => {
      expect(
        screen.getByText("I couldn't write an answer right now. Please try again."),
      ).toBeInTheDocument();
    });

    const tryAgainBtn = screen.getByRole('button', { name: 'Try again' });
    await user.click(tryAgainBtn);

    // Confirms: POST body query === "Q1", never msg.content and not lastSentQuery
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/chat/stream',
        expect.objectContaining({
          body: JSON.stringify({
            session_id: 'sess-saved-retry',
            query: 'Q1',
          }),
        }),
      );
    });
  });

  it('2. Refill effect: clearing the input after an AGENT_BUSY notice leaves the input empty', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: mockSessionSummary,
      requestId: 'req-sess',
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'The service is busy. Please try again shortly.',
          code: 'AGENT_BUSY',
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    await user.type(input, 'What are the risks?');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Wait for error notice and input preserved
    await waitFor(() => {
      expect(
        screen.getByText('The service is busy. Please try again shortly.'),
      ).toBeInTheDocument();
    });
    expect(input.value).toBe('What are the risks?');

    // User clears the input
    await user.clear(input);
    expect(input.value).toBe('');

    // Crucial check: input STAYS empty and does not refill because streamError hasn't changed
    expect(input.value).toBe('');
  });

  it('3. Stream returning 503 DEPENDENCY_UNAVAILABLE shows inline notice with question kept in input', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: mockSessionSummary,
      requestId: 'req-sess-dep',
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'Vector database unreachable.',
          code: 'DEPENDENCY_UNAVAILABLE',
        }),
        {
          status: 503,
          headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': 'req-dep-unavailable',
          },
        },
      ),
    );

    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question') as HTMLInputElement;
    await user.type(input, 'Query with unavailable vector DB');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Shows inline notice (not full-page ServiceUnavailablePage)
    await waitFor(() => {
      expect(
        screen.getByText('Vector database unreachable.'),
      ).toBeInTheDocument();
    });

    // Request ID shown
    expect(screen.getByText('Request ID: req-dep-unavailable')).toBeInTheDocument();

    // Full page service unavailable NOT rendered
    expect(
      screen.queryByText('Service Temporarily Unavailable'),
    ).not.toBeInTheDocument();

    // Question kept in the input
    expect(input.value).toBe('Query with unavailable vector DB');
  });

  it('4. "+ New" clears state and navigates to /chat without calling createSession', async () => {
    const postSpy = vi.spyOn(clientModule, 'apiPost');
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions/sess-100')) {
        return Promise.resolve({ data: mockSessionDetail, requestId: 'req-2' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-3' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat/sess-100');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByText('Financial Review')).toBeInTheDocument();
    });

    const newButtons = screen.getAllByRole('button', { name: '+ New' });
    expect(newButtons.length).toBeGreaterThan(0);

    // Click "+ New"
    await user.click(newButtons[0]);

    // Navigates to clean /chat
    expect(window.location.pathname).toBe('/chat');

    // Confirms: MUST NOT call createSession
    expect(postSpy).not.toHaveBeenCalledWith('/sessions', expect.anything());
  });

  it('5. hasDocuments: only failed documents -> "Your documents could not be processed." is shown and send is disabled', async () => {
    const onlyFailedDocs: Document[] = [
      {
        document_id: 'doc-fail-1',
        filename: 'broken.pdf',
        status: 'failed',
        error_message: 'Parsing failed',
        source_type: 'pdf',
        created_at: '2026-10-31T00:00:00Z',
        uploaded_by_me: true,
      },
    ];

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: onlyFailedDocs, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Your documents could not be processed.' }),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByPlaceholderText('Your documents could not be processed...'),
    ).toBeInTheDocument();

    const sendBtn = screen.getByRole('button', { name: /send/i });
    expect(sendBtn).toBeDisabled();
  });
});

describe('12. Chat.tsx Sidebar & Empty State UX Fixes', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sidebar shows "Couldn\'t load conversations." with Retry button when sessions query fails', async () => {
    let callCount = 0;
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        callCount++;
        if (callCount === 1) {
          const err = new clientModule.ApiRequestError({
            error: 'Failed to load sessions',
            code: 'INTERNAL_ERROR',
            status: 500,
            requestId: 'req-err',
            retryAfter: null,
          });
          return Promise.reject(err);
        }
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    const user = userEvent.setup();
    renderWithProviders(<Chat />);

    // Shows "Couldn't load conversations." with a Retry button
    await waitFor(() => {
      expect(screen.getByText("Couldn't load conversations.")).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    expect(retryBtn).toBeInTheDocument();

    // Clicking Retry refetches
    await user.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('Financial Review')).toBeInTheDocument();
    });
  });

  it('sidebar shows "No conversations yet." when sessions query succeeds with empty list', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(screen.getByText('No conversations yet.')).toBeInTheDocument();
    });
    expect(screen.queryByText("Couldn't load conversations.")).not.toBeInTheDocument();
  });

  it('empty state (a): no documents at all -> "Upload a document first", placeholder, Send disabled', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: [], requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Upload a document first' }),
      ).toBeInTheDocument();
    });

    expect(screen.getByPlaceholderText('Upload a document first...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Go to Documents' })).toHaveAttribute('href', '/documents');
  });

  it('empty state (b): documents exist with queued/parsing/indexing -> "Your document is still being processed...", placeholder, Send disabled', async () => {
    const processingDocs: Document[] = [
      {
        document_id: 'doc-proc-1',
        filename: 'data.pdf',
        status: 'parsing',
        error_message: null,
        source_type: 'pdf',
        created_at: '2026-10-31T00:00:00Z',
        uploaded_by_me: true,
      },
    ];

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: processingDocs, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', {
          name: 'Your document is still being processed. You can ask questions when it is ready.',
        }),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByPlaceholderText('Your document is still being processed...'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Go to Documents' })).toHaveAttribute('href', '/documents');
  });

  it('empty state (c): documents exist and all are failed -> "Your documents could not be processed.", placeholder, Send disabled', async () => {
    const allFailedDocs: Document[] = [
      {
        document_id: 'doc-fail-1',
        filename: 'broken.pdf',
        status: 'failed',
        error_message: 'Corrupt file',
        source_type: 'pdf',
        created_at: '2026-10-31T00:00:00Z',
        uploaded_by_me: true,
      },
    ];

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: allFailedDocs, requestId: 'req-1' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-2' });
      }
      return Promise.reject(new Error(`Unhandled ${url}`));
    });

    window.history.pushState({}, '', '/chat');
    renderWithProviders(<Chat />);

    await waitFor(() => {
      expect(
        screen.getByRole('heading', {
          name: 'Your documents could not be processed.',
        }),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByPlaceholderText('Your documents could not be processed...'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Go to Documents' })).toHaveAttribute('href', '/documents');
  });
});

