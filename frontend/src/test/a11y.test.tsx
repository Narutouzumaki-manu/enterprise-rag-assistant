import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { ReactElement } from 'react';
import { AuthProvider } from '../hooks/useAuth';
import { Login, getSafeRedirect } from '../pages/Login';
import { Documents } from '../pages/Documents';
import { Chat } from '../pages/Chat';
import { DocumentRow } from '../components/DocumentRow';
import { CitationCard } from '../components/CitationCard';
import { ServiceUnavailablePage } from '../components/ErrorState';
import { clearToken } from '../api/tokenStore';
import * as clientModule from '../api/client';
import type { SessionDetail, SessionSummary, Document } from '../api/types';
import { EXAMPLE_QUESTIONS } from '../constants';

const axeOptions = {
  rules: {
    'color-contrast': { enabled: false },
  },
};

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

const mockSavedSession: SessionDetail = {
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
          chunk_id: 'chunk-1',
          document_id: 'doc-1',
          source_file: 'annual_report.pdf',
          page_number: 14,
          text_snippet: 'Q3 revenue reached $4.2B, an increase of 8%.',
        },
      ],
      trace: [
        {
          step_type: 'retrieve',
          content: 'Searching documents for Q3 revenue',
          metadata: {},
        },
      ],
    },
  ],
};

function renderWithProviders(ui: ReactElement, initialRoute = '/chat') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/chat" element={ui} />
            <Route path="/chat/:sessionId" element={ui} />
            <Route path="*" element={ui} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Accessibility & UI Polish (vitest-axe and interactions)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    clearToken();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 1. vitest-axe: 0 violations checks
  // ───────────────────────────────────────────────────────────────────────────

  it('Login page has 0 axe violations', async () => {
    const { container } = renderWithProviders(<Login />, '/login');
    expect(screen.getByRole('heading', { level: 1, name: 'Enterprise RAG Assistant' })).toBeInTheDocument();

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it('Documents page with delete confirmation dialog open has 0 axe violations', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const user = userEvent.setup();
    const { container } = renderWithProviders(<Documents />, '/documents');

    // Wait for document row to appear
    await waitFor(() => {
      expect(screen.getByText('annual_report.pdf')).toBeInTheDocument();
    });

    // Click Delete button to open confirmation dialog
    const deleteBtn = screen.getByRole('button', { name: 'Delete annual_report.pdf' });
    await user.click(deleteBtn);

    // Verify dialog is open
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it('Chat page (a. empty conversation with ready docs & starter examples) has 0 axe violations', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const { container } = renderWithProviders(<Chat />, '/chat');

    await waitFor(() => {
      expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
    });

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it('Chat page (b. saved conversation with citations & ratings) has 0 axe violations', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: mockSavedSession, requestId: 'req-sess-detail' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const { container } = renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByText('The Q3 revenue was $4.2B.')).toBeInTheDocument();
    });

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it('Chat page (c. live streaming with steps panel, in-progress step & streaming answer) has 0 axe violations', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(
          new TextEncoder().encode(
            'event: status\ndata: {"step_type":"retrieve","content":"Searching knowledge base"}\n\n' +
            'event: token\ndata: {"text":"Projected revenue is $5B."}\n\n',
          ),
        );
      },
    });

    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (typeof input === 'string' && input.includes('/chat/stream')) {
        return Promise.resolve(new Response(stream, { status: 200 }));
      }
      return Promise.reject(new Error(`Unhandled fetch ${String(input)}`));
    });

    const user = userEvent.setup();
    const { container } = renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText('Ask a question'), 'What is the projection?');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByText('Searching knowledge base')).toBeInTheDocument();
      expect(screen.getByText('Projected revenue is $5B.')).toBeInTheDocument();
    });

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  it('Chat page (d. error notice with inline AGENT_BUSY notice) has 0 axe violations', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'The service is currently overloaded. Please try again.',
          code: 'AGENT_BUSY',
          retry_after: 5,
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const user = userEvent.setup();
    const { container } = renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText('Ask a question'), 'Hello');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('The service is currently overloaded. Please try again.')).toBeInTheDocument();
    });

    const results = await axe(container, axeOptions);
    expect(results).toHaveNoViolations();
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 2. Mobile Drawer Navigation & Focus Trap / Restoration
  // ───────────────────────────────────────────────────────────────────────────

  it('Drawer: opening mobile drawer moves focus in; Escape closes it and returns focus to opener button', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<Chat />, '/chat');

    const openerBtn = screen.getByRole('button', { name: 'Open conversation history drawer' });
    openerBtn.focus();
    expect(document.activeElement).toBe(openerBtn);

    // Open drawer
    await user.click(openerBtn);

    // Drawer dialog should be visible and focus should move inside it
    const drawerDialog = screen.getByRole('dialog', { name: 'Conversations' });
    expect(drawerDialog).toBeInTheDocument();
    expect(drawerDialog).toContainElement(document.activeElement as HTMLElement | null);

    // Press Escape
    fireEvent.keyDown(window, { key: 'Escape' });

    // Drawer dialog should be closed (no longer role=dialog for mobile)
    expect(screen.queryByRole('dialog', { name: 'Conversations' })).not.toBeInTheDocument();

    // Focus must return to opener button
    expect(document.activeElement).toBe(openerBtn);
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 3. Question Input Length Limit (2000 chars)
  // ───────────────────────────────────────────────────────────────────────────

  it('Input: typing/pasting 2001 chars shows red counter, error message, and disables Send; deleting 1 char re-enables Send', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    renderWithProviders(<Chat />, '/chat');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question');
    const sendBtn = screen.getByRole('button', { name: /send/i });

    // 1. Enter 2001 characters
    fireEvent.change(input, { target: { value: 'a'.repeat(2001) } });

    // Counter turns red (text-rose-600)
    const counter = screen.getByText('2001/2000');
    expect(counter.className).toContain('text-rose-600');

    // Error message displayed politely
    expect(screen.getByText('Questions must be 2000 characters or fewer.')).toBeInTheDocument();

    // Send button disabled
    expect(sendBtn).toBeDisabled();

    // 2. Delete 1 character (back to 2000 characters)
    fireEvent.change(input, { target: { value: 'a'.repeat(2000) } });

    // Counter turns neutral
    const neutralCounter = screen.getByText('2000/2000');
    expect(neutralCounter.className).not.toContain('text-rose-600');

    // Error message disappeared
    expect(screen.queryByText('Questions must be 2000 characters or fewer.')).not.toBeInTheDocument();

    // Send button enabled
    expect(sendBtn).not.toBeDisabled();
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 4. Delete Dialog in DocumentRow
  // ───────────────────────────────────────────────────────────────────────────

  it('Delete dialog in DocumentRow: clicking Delete opens dialog, focus moves in, pressing Escape cancels and returns focus', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);

    render(
      <table>
        <tbody>
          <DocumentRow
            doc={mockDocuments[0]}
            onDelete={onDelete}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    const deleteBtn = screen.getByRole('button', { name: 'Delete annual_report.pdf' });
    deleteBtn.focus();
    expect(document.activeElement).toBe(deleteBtn);

    // Open confirmation dialog
    await user.click(deleteBtn);

    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toContainElement(document.activeElement as HTMLElement | null);

    // Press Escape
    fireEvent.keyDown(window, { key: 'Escape' });

    // Dialog closes
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    // Focus returns to Delete button
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Delete annual_report.pdf' }));
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 5. Skip to Main Content Link
  // ───────────────────────────────────────────────────────────────────────────

  it('Skip link: first focusable element on page, target #main-content has tabIndex={-1} and receives focus on click', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />, '/login');

    const skipLink = screen.getByRole('link', { name: 'Skip to main content' });
    expect(skipLink).toBeInTheDocument();

    // Target element exists and has tabIndex -1
    const mainContent = document.getElementById('main-content');
    expect(mainContent).not.toBeNull();
    expect(mainContent).toHaveAttribute('tabIndex', '-1');

    // Click skip link
    await user.click(skipLink);

    // Main content receives focus
    expect(document.activeElement).toBe(mainContent);
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 6. Stage 1b Specific Tests
  // ───────────────────────────────────────────────────────────────────────────

  it('1. closed mobile drawer is not focusable at mobile width; desktop sidebar is focusable', async () => {
    // Set mobile width < 1024
    window.innerWidth = 500;
    fireEvent(window, new Event('resize'));

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    renderWithProviders(<Chat />, '/chat');

    await waitFor(() => {
      expect(screen.getByLabelText('Open conversation history drawer')).toBeInTheDocument();
    });

    const aside = document.querySelector('aside');
    expect(aside).not.toBeNull();
    // Drawer is closed: aside has inert and visibility: hidden
    expect(aside).toHaveAttribute('inert');
    expect(aside).toHaveAttribute('aria-hidden', 'true');
    expect(aside?.style.visibility).toBe('hidden');

    // All buttons inside closed mobile drawer have tabIndex -1
    const sidebarButtons = aside!.querySelectorAll('button');
    expect(sidebarButtons.length).toBeGreaterThan(0);
    sidebarButtons.forEach((btn) => {
      expect(btn).toHaveAttribute('tabIndex', '-1');
    });

    // Now resize to desktop width >= 1024
    window.innerWidth = 1200;
    fireEvent(window, new Event('resize'));

    await waitFor(() => {
      expect(aside?.style.visibility).toBe('visible');
    });
    expect(aside).not.toHaveAttribute('inert');
    expect(aside).not.toHaveAttribute('aria-hidden');

    // Buttons are now normally focusable (not tabIndex -1)
    sidebarButtons.forEach((btn) => {
      expect(btn).not.toHaveAttribute('tabIndex', '-1');
    });
  });

  it('2. status announcement: empty during token streaming, announces "Answer ready. <trust text>." once on finish', async () => {
    window.innerWidth = 1024;
    fireEvent(window, new Event('resize'));

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
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

    const user = userEvent.setup();
    renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    // Check persistent announcement element exists from first render
    const announcementEl = screen.getByTestId('stream-announcement');
    expect(announcementEl).toBeInTheDocument();
    expect(announcementEl).toHaveAttribute('role', 'status');
    expect(announcementEl).toHaveAttribute('aria-live', 'polite');
    expect(announcementEl.textContent).toBe('');

    await user.type(screen.getByLabelText('Ask a question'), 'What is the projection?');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Send token: announcement must NOT be set while tokens stream
    streamController!.enqueue(
      new TextEncoder().encode(
        'event: token\ndata: {"text":"Projected revenue is $5B."}\n\n'
      ),
    );

    await waitFor(() => {
      expect(screen.getByText('Projected revenue is $5B.')).toBeInTheDocument();
    });
    // Announcement remains empty while streaming tokens
    expect(announcementEl.textContent).toBe('');

    // Stream completes with verification and done
    streamController!.enqueue(
      new TextEncoder().encode(
        'event: verification\ndata: {"status":"verified"}\n\n' +
        'event: done\ndata: {}\n\n'
      ),
    );
    streamController!.close();

    // After finish: announced exactly once
    await waitFor(() => {
      expect(announcementEl.textContent).toBe('Answer ready. Found in your documents.');
    });
  });

  it('2b. status announcement announces matching error message on pre-stream error', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: 'The service is currently overloaded. Please try again.',
          code: 'AGENT_BUSY',
          retry_after: 5,
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const announcementEl = screen.getByTestId('stream-announcement');
    await user.type(screen.getByLabelText('Ask a question'), 'Hello');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(announcementEl.textContent).toContain('The service is currently overloaded. Please try again.');
    });
  });

  it('3. focus restoration after stream: restores focus only if body/input active, does not restore if focus elsewhere or mobile <640px', async () => {
    // Condition 1: desktop >= 640px, focus on document.body -> restored to input
    window.innerWidth = 800;
    fireEvent(window, new Event('resize'));

    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url === '/sessions/sess-100') {
        return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    let streamController: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        streamController = c;
      },
    });

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(stream, { status: 200 }));

    const user = userEvent.setup();
    renderWithProviders(<Chat />, '/chat/sess-100');

    await waitFor(() => {
      expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
    });

    const input = screen.getByLabelText('Ask a question');
    await user.type(input, 'Query{enter}');

    // When form submits and stream runs, simulate body activeElement
    document.body.tabIndex = -1;
    document.body.focus();
    expect(document.activeElement).toBe(document.body);

    // Stream completes
    streamController!.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'));
    streamController!.close();

    // At >=640px with body active, focus is restored to input
    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });

    // Condition 1b: If focus is on another interactive element, focus is NOT stolen
    const newBtn = screen.getByRole('button', { name: '+ New' });
    newBtn.focus();
    expect(document.activeElement).toBe(newBtn);

    let streamControllerOther: ReadableStreamDefaultController<Uint8Array>;
    const streamOther = new ReadableStream<Uint8Array>({
      start(c) {
        streamControllerOther = c;
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(streamOther, { status: 200 }));

    await user.type(input, 'Another query');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Move focus to another button while stream is running
    newBtn.focus();
    expect(document.activeElement).toBe(newBtn);

    streamControllerOther!.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'));
    streamControllerOther!.close();

    await new Promise((r) => setTimeout(r, 100));
    // Focus was NOT stolen by input
    expect(document.activeElement).toBe(newBtn);

    // Condition 2: mobile < 640px -> focus is NOT restored to input
    window.innerWidth = 400;
    fireEvent(window, new Event('resize'));

    let streamController2: ReadableStreamDefaultController<Uint8Array>;
    const stream2 = new ReadableStream<Uint8Array>({
      start(c) {
        streamController2 = c;
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(stream2, { status: 200 }));

    await user.type(input, 'Second query');
    await user.click(screen.getByRole('button', { name: /send/i }));

    streamController2!.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'));
    streamController2!.close();

    // Wait a moment for any potential stream completion effect
    await new Promise((r) => setTimeout(r, 100));

    // Focus must NOT be restored to input on mobile
    expect(document.activeElement).not.toBe(input);

    // Focus must NOT be restored to input on mobile
    expect(document.activeElement).not.toBe(input);

    // Reset window width
    window.innerWidth = 1024;
    fireEvent(window, new Event('resize'));
  });

  it('4. chat page has Skip link as first focusable element, pointing to <main id="main-content" tabIndex={-1}>', async () => {
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url.startsWith('/documents')) {
        return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
      }
      if (url.startsWith('/sessions')) {
        return Promise.resolve({ data: [], requestId: 'req-sessions' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<Chat />, '/chat');

    const skipLink = screen.getByRole('link', { name: 'Skip to main content' });
    expect(skipLink).toBeInTheDocument();

    const mainContent = document.getElementById('main-content');
    expect(mainContent).not.toBeNull();
    expect(mainContent).toHaveAttribute('tabIndex', '-1');

    await user.click(skipLink);
    expect(document.activeElement).toBe(mainContent);
  });

  it('5. safe login redirect: accepts "/documents", rejects "//evil.example", "/\\evil", "https://x.y", "javascript:alert(1)"', () => {
    expect(getSafeRedirect('/documents')).toBe('/documents');
    expect(getSafeRedirect('//evil.example')).toBe('/chat');
    expect(getSafeRedirect('/\\evil')).toBe('/chat');
    expect(getSafeRedirect('https://x.y')).toBe('/chat');
    expect(getSafeRedirect('javascript:alert(1)')).toBe('/chat');

    // Whitespace and control character rejection
    expect(getSafeRedirect('/\t/evil.example')).toBe('/chat');
    expect(getSafeRedirect('/ evil')).toBe('/chat');
    expect(getSafeRedirect('/evil\n')).toBe('/chat');
    expect(getSafeRedirect('/evil\r\n')).toBe('/chat');
    expect(getSafeRedirect('/\u0000evil')).toBe('/chat');
    expect(getSafeRedirect('/\u001fevil')).toBe('/chat');

    // Additional boundary edge cases
    expect(getSafeRedirect(null)).toBe('/chat');
    expect(getSafeRedirect('')).toBe('/chat');
    expect(getSafeRedirect('/nested/path?query=1')).toBe('/nested/path?query=1');
  });

  it('6. citation cards: remove tabIndex={0} and keep readable structure with source and page', () => {
    const citation = {
      chunk_id: 'c-1',
      document_id: 'doc-1',
      source_file: 'sales_2026.pdf',
      page_number: 12,
      text_snippet: 'Revenue grew by 15% in Q4.',
    };

    const { container } = render(<CitationCard citation={citation} />);
    const article = container.querySelector('article');
    expect(article).not.toBeNull();
    expect(article).not.toHaveAttribute('tabindex');
    expect(screen.getByText('sales_2026.pdf, p. 12')).toBeInTheDocument();
    expect(screen.getByText(/Revenue grew by 15% in Q4/)).toBeInTheDocument();
  });

  it('7. ErrorState restores previous document.title on unmount', () => {
    document.title = 'Previous App Title';

    const { unmount } = render(
      <ServiceUnavailablePage onRetry={vi.fn()} requestId="req-123" />,
    );

    expect(document.title).toBe('Service Unavailable - Enterprise RAG Assistant');

    unmount();

    expect(document.title).toBe('Previous App Title');
  });

  // ───────────────────────────────────────────────────────────────────────────
  // 8. Heading hierarchy & single h1 checks (Login, Documents, Chat states)
  // ───────────────────────────────────────────────────────────────────────────

  describe('Heading hierarchy checks (single h1 and levels never skip downward)', () => {
    function assertHeadingHierarchy(container: HTMLElement) {
      const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6')) as HTMLElement[];
      const h1s = container.querySelectorAll('h1');
      expect(h1s.length).toBe(1);

      const levels = headings.map((h) => parseInt(h.tagName.substring(1), 10));
      expect(levels.length).toBeGreaterThan(0);
      expect(levels[0]).toBe(1);

      for (let i = 1; i < levels.length; i++) {
        expect(levels[i]).toBeLessThanOrEqual(levels[i - 1] + 1);
      }
      return headings.map((h) => ({ level: h.tagName.toLowerCase(), text: h.textContent?.trim() || '' }));
    }

    it('Login page has exactly one h1 and valid heading hierarchy', () => {
      const { container } = renderWithProviders(<Login />, '/login');
      const outline = assertHeadingHierarchy(container);
      expect(outline).toEqual([
        { level: 'h1', text: 'Enterprise RAG Assistant' },
      ]);
    });

    it('Documents page has exactly one h1 and valid heading hierarchy', async () => {
      vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
        if (url.startsWith('/documents')) {
          return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
        }
        return Promise.reject(new Error(`Unhandled GET ${url}`));
      });

      const { container } = renderWithProviders(<Documents />, '/documents');
      await waitFor(() => {
        expect(screen.getByText('annual_report.pdf')).toBeInTheDocument();
      });

      const outline = assertHeadingHierarchy(container);
      expect(outline).toEqual([
        { level: 'h1', text: 'Documents' },
        { level: 'h2', text: 'Upload Documents' },
        { level: 'h2', text: 'Uploaded Documents (1)' },
      ]);
    });

    it('Chat empty state has exactly one h1 and valid heading hierarchy', async () => {
      vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
        if (url.startsWith('/documents')) {
          return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
        }
        if (url.startsWith('/sessions')) {
          return Promise.resolve({ data: [], requestId: 'req-sessions' });
        }
        return Promise.reject(new Error(`Unhandled GET ${url}`));
      });

      const { container } = renderWithProviders(<Chat />, '/chat');
      await waitFor(() => {
        expect(screen.getByText(EXAMPLE_QUESTIONS[0])).toBeInTheDocument();
      });

      const outline = assertHeadingHierarchy(container);
      expect(outline).toEqual([
        { level: 'h1', text: 'Chat' },
        { level: 'h2', text: 'Conversations' },
        { level: 'h2', text: 'Ask a question about your uploaded documents' },
      ]);
    });

    it('Chat saved conversation has exactly one h1 and valid heading hierarchy', async () => {
      vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
        if (url.startsWith('/documents')) {
          return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
        }
        if (url === '/sessions/sess-100') {
          return Promise.resolve({ data: mockSavedSession, requestId: 'req-sess-detail' });
        }
        if (url.startsWith('/sessions')) {
          return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
        }
        return Promise.reject(new Error(`Unhandled GET ${url}`));
      });

      const { container } = renderWithProviders(<Chat />, '/chat/sess-100');
      await waitFor(() => {
        expect(screen.getByText('The Q3 revenue was $4.2B.')).toBeInTheDocument();
      });

      const outline = assertHeadingHierarchy(container);
      expect(outline).toEqual([
        { level: 'h1', text: 'Chat' },
        { level: 'h2', text: 'Conversations' },
        { level: 'h3', text: 'Sources (1)' },
      ]);
    });

    it('Chat live streaming has exactly one h1 and valid heading hierarchy', async () => {
      vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
        if (url.startsWith('/documents')) {
          return Promise.resolve({ data: mockDocuments, requestId: 'req-docs' });
        }
        if (url === '/sessions/sess-100') {
          return Promise.resolve({ data: { ...mockSessionSummary, messages: [] }, requestId: 'req-sess' });
        }
        if (url.startsWith('/sessions')) {
          return Promise.resolve({ data: [mockSessionSummary], requestId: 'req-sessions' });
        }
        return Promise.reject(new Error(`Unhandled GET ${url}`));
      });

      const stream = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(
            new TextEncoder().encode(
              'event: status\ndata: {"step_type":"retrieve","content":"Searching knowledge base"}\n\n' +
              'event: token\ndata: {"text":"Projected revenue is $5B."}\n\n',
            ),
          );
        },
      });

      vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
        if (typeof input === 'string' && input.includes('/chat/stream')) {
          return Promise.resolve(new Response(stream, { status: 200 }));
        }
        return Promise.reject(new Error(`Unhandled fetch ${String(input)}`));
      });

      const user = userEvent.setup();
      const { container } = renderWithProviders(<Chat />, '/chat/sess-100');

      await waitFor(() => {
        expect(screen.getByLabelText('Ask a question')).toBeInTheDocument();
      });

      await user.type(screen.getByLabelText('Ask a question'), 'What is the projection?');
      await user.click(screen.getByRole('button', { name: /send/i }));

      await waitFor(() => {
        expect(screen.getByText('Searching knowledge base')).toBeInTheDocument();
        expect(screen.getByText('Projected revenue is $5B.')).toBeInTheDocument();
      });

      const outline = assertHeadingHierarchy(container);
      expect(outline).toEqual([
        { level: 'h1', text: 'Chat' },
        { level: 'h2', text: 'Conversations' },
      ]);
    });
  });
});
