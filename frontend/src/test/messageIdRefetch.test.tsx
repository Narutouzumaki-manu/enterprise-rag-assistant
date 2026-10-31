import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RatingButtons } from '../components/RatingButtons';
import { useChatStream } from '../hooks/useChatStream';
import * as clientModule from '../api/client';
import type { SessionDetail } from '../api/types';

function RatingTestHarness() {
  const { sendQuery, messageId, messageIdFailed, reloadMessageId } = useChatStream();

  return (
    <div>
      <button
        type="button"
        onClick={() => void sendQuery('sess-test', 'hello')}
      >
        Send Stream
      </button>
      <RatingButtons
        messageId={messageId}
        messageIdFailed={messageIdFailed}
        onReloadRating={reloadMessageId}
      />
    </div>
  );
}

describe('Message-ID Refetch & Rating Buttons Lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps thumbs buttons disabled when messageId is null (pre-refetch)', () => {
    render(<RatingButtons messageId={null} />);
    const thumbsUp = screen.getByLabelText('Thumbs up - answer was helpful');
    const thumbsDown = screen.getByLabelText('Thumbs down - answer was not helpful');

    expect(thumbsUp).toBeDisabled();
    expect(thumbsDown).toBeDisabled();
  });

  it('enables thumbs buttons once messageId arrives after session refetch', async () => {
    const { rerender } = render(<RatingButtons messageId={null} />);

    expect(screen.getByLabelText('Thumbs up - answer was helpful')).toBeDisabled();

    // Rerender with resolved messageId from session refetch
    rerender(<RatingButtons messageId="msg-asst-refetched" />);

    const thumbsUp = screen.getByLabelText('Thumbs up - answer was helpful');
    const thumbsDown = screen.getByLabelText('Thumbs down - answer was not helpful');

    expect(thumbsUp).not.toBeDisabled();
    expect(thumbsDown).not.toBeDisabled();
  });

  it('rating again replaces the previous rating and sends POST /feedback', async () => {
    const apiPostSpy = vi.spyOn(clientModule, 'apiPost').mockResolvedValue({
      data: { message_id: 'msg-123', rating: 1, comment: null },
      requestId: 'req-fb',
    });

    const user = userEvent.setup();
    render(<RatingButtons messageId="msg-123" />);

    const thumbsUp = screen.getByLabelText('Thumbs up - answer was helpful');
    const thumbsDown = screen.getByLabelText('Thumbs down - answer was not helpful');

    // First: Thumbs Up
    await user.click(thumbsUp);
    expect(apiPostSpy).toHaveBeenCalledWith('/feedback', {
      message_id: 'msg-123',
      rating: 1,
    });

    // Second: Replace with Thumbs Down
    apiPostSpy.mockResolvedValueOnce({
      data: { message_id: 'msg-123', rating: -1, comment: null },
      requestId: 'req-fb-2',
    });

    await user.click(thumbsDown);
    expect(apiPostSpy).toHaveBeenCalledWith('/feedback', {
      message_id: 'msg-123',
      rating: -1,
    });
  });

  it('refetch fails twice -> note and button shown; button click with a successful refetch -> rating buttons enabled', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    // Mock stream endpoint to complete immediately with 'done'
    const sseResponse = new Response('event: done\ndata: {}\n\n', {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(sseResponse);

    const mockSuccessSession: SessionDetail = {
      session_id: 'sess-test',
      title: 'Test Session',
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
      messages: [
        {
          message_id: 'msg-recovered-999',
          role: 'assistant',
          content: 'Here is the answer.',
          created_at: '2026-10-31T00:00:00Z',
          verification_status: 'verified',
          confidence: null,
          latency_ms: null,
          citations: [],
          trace: [],
        },
      ],
    };

    let apiGetCallCount = 0;
    vi.spyOn(clientModule, 'apiGet').mockImplementation((url: string) => {
      if (url === '/sessions/sess-test') {
        apiGetCallCount++;
        if (apiGetCallCount <= 2) {
          return Promise.reject(new Error('Network error on session refetch'));
        }
        return Promise.resolve({ data: mockSuccessSession, requestId: 'req-rec' });
      }
      return Promise.reject(new Error(`Unhandled GET ${url}`));
    });

    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <RatingTestHarness />
      </QueryClientProvider>,
    );

    // Initial state: thumbs buttons disabled, no error note
    expect(screen.getByLabelText('Thumbs up - answer was helpful')).toBeDisabled();
    expect(screen.queryByText('Rating is unavailable right now')).not.toBeInTheDocument();

    // Trigger stream
    await user.click(screen.getByRole('button', { name: 'Send Stream' }));

    // Wait for the stream to finish and the 1.5s retry timer to complete
    await new Promise((r) => setTimeout(r, 1800));

    // Both refetches failed: note and "Reload to rate" button must be shown
    expect(screen.getByText('Rating is unavailable right now')).toBeInTheDocument();
    const reloadBtn = screen.getByRole('button', { name: /reload to rate/i });
    expect(reloadBtn).toBeInTheDocument();
    expect(screen.getByLabelText('Thumbs up - answer was helpful')).toBeDisabled();

    // Click "Reload to rate" button with successful refetch
    await user.click(reloadBtn);

    // Rating buttons must now be enabled and the error note removed
    expect(screen.getByLabelText('Thumbs up - answer was helpful')).not.toBeDisabled();
    expect(screen.getByLabelText('Thumbs down - answer was not helpful')).not.toBeDisabled();
    expect(screen.queryByText('Rating is unavailable right now')).not.toBeInTheDocument();
  }, 10000);
});

