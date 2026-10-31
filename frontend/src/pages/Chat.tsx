// ─────────────────────────────────────────────────────────────────────────────
// Chat.tsx — Main chat conversation interface.
//
// Rules:
//   - Sessions list on the left (drawer on mobile <360px), sorted by updated_at desc.
//   - Empty states: "Upload a document first" / EXAMPLE_QUESTIONS starter buttons.
//   - Example questions ONLY fill the input box; never send automatically.
//   - Pre-stream errors 503 AGENT_BUSY & 429 inline with countdown, keeping query.
//   - Full-page unavailable screen ONLY for DEPENDENCY_UNAVAILABLE.
//   - While streaming: AgentSteps with elapsed timer, "Stop waiting" button.
//   - Finished answers: collapsed "N steps", TrustBadge, Citations, Rating.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { NavBar } from '../components/NavBar';
import { AgentSteps } from '../components/AgentSteps';
import { AnswerCard } from '../components/AnswerCard';
import { ServiceUnavailablePage, InlineErrorNotice } from '../components/ErrorState';
import { useSessions, useSessionDetail } from '../hooks/useSessions';
import { useDocuments } from '../hooks/useDocuments';
import { useChatStream } from '../hooks/useChatStream';
import { EXAMPLE_QUESTIONS, CONNECTION_LOST_MESSAGE } from '../constants';
import type { Message } from '../api/types';

export function Chat() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();

  // Sessions and Document data
  const {
    sessions,
    isLoadingSessions,
    isSessionsError,
    sessionsError,
    refetchSessions,
    createSession,
  } = useSessions();
  const { session: currentSession, isLoading: isLoadingSession, error: sessionError, refetch: refetchSession } =
    useSessionDetail(sessionId);
  const { documents, isLoading: isLoadingDocs } = useDocuments();

  // Chat Streaming
  const {
    isStreaming,
    activeSessionId,
    steps,
    answer,
    citations,
    verificationStatus,
    streamStartTime,
    messageId,
    messageIdFailed,
    reloadMessageId,
    streamError,
    setStreamError,
    isConnectionLost,
    isAborted,
    sendQuery,
    stopWaiting,
    resetStream,
  } = useChatStream();

  // Form & UI state
  const [queryInput, setQueryInput] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [lastSentQuery, setLastSentQuery] = useState('');

  // 404 & 422 session handling: treat as conversation not found and return to new conversation
  useEffect(() => {
    if (sessionError && (sessionError.status === 404 || sessionError.status === 422)) {
      navigate('/chat', { replace: true });
    }
  }, [sessionError, navigate]);

  // Handle switching conversations during a stream
  useEffect(() => {
    if (isStreaming && activeSessionId && activeSessionId !== sessionId) {
      stopWaiting(); // abort; the server still saves the answer
      resetStream();
    } else if (!isStreaming) {
      resetStream(); // clear leftover error / connection-lost state
    }
    // streaming AND same session: do nothing
  }, [sessionId]);

  // Refill input after error (runs only when a new streamError appears)
  useEffect(() => {
    if (streamError) {
      setQueryInput((prev) => prev || lastSentQuery);
    }
  }, [streamError]);

  const handleCreateNewSession = () => {
    resetStream();
    setQueryInput('');
    setValidationError(null);
    setMobileDrawerOpen(false);
    navigate('/chat');
  };

  const handleSend = async (textToSend?: string) => {
    const text = (textToSend ?? queryInput).trim();

    // Client-side validation: 1 to 2000 chars, not blank
    if (!text) {
      setValidationError('Please enter a question.');
      return;
    }
    if (text.length > 2000) {
      setValidationError('Questions must be 2000 characters or fewer.');
      return;
    }

    setValidationError(null);
    setLastSentQuery(text);

    let targetSessionId = sessionId;
    if (!targetSessionId) {
      try {
        const newSession = await createSession();
        targetSessionId = newSession.session_id;
        navigate(`/chat/${targetSessionId}`, { replace: true });
      } catch {
        setStreamError({
          error: CONNECTION_LOST_MESSAGE,
          code: 'INTERNAL_ERROR',
          status: 0,
          retryAfter: null,
          requestId: null,
        });
        return;
      }
    }

    // Clear input box
    setQueryInput('');

    // Stream query
    await sendQuery(targetSessionId, text);
  };

  const handleExampleClick = (example: string) => {
    // Contract requirement: Clicking an example only fills the question box; NEVER sends automatically!
    setQueryInput(example);
    setValidationError(null);
  };

  // Full page Service Unavailable condition
  if (sessionError && sessionError.code === 'DEPENDENCY_UNAVAILABLE') {
    return (
      <ServiceUnavailablePage
        requestId={sessionError.requestId}
        onRetry={() => {
          resetStream();
          void refetchSession();
        }}
      />
    );
  }

  const hasDocuments = documents.some(
    (doc) => doc.status === 'success' || doc.status === 'partial',
  );
  const hasProcessingDocs =
    !hasDocuments &&
    documents.some(
      (doc) =>
        doc.status === 'queued' ||
        doc.status === 'parsing' ||
        doc.status === 'indexing',
    );
  const hasAllFailedDocs =
    !hasDocuments &&
    documents.length > 0 &&
    documents.every((doc) => doc.status === 'failed');

  let docPlaceholder = 'Upload a document first...';
  if (hasDocuments) {
    docPlaceholder = 'Ask a question about your documents...';
  } else if (hasProcessingDocs) {
    docPlaceholder = 'Your document is still being processed...';
  } else if (hasAllFailedDocs) {
    docPlaceholder = 'Your documents could not be processed...';
  }

  const messages: Message[] = currentSession?.messages ?? [];
  const showStarterExamples = !isStreaming && messages.length === 0;

  return (
    <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <NavBar />

      <div className="flex-1 flex overflow-hidden max-w-7xl w-full mx-auto">
        {/* Mobile drawer toggle */}
        <div className="lg:hidden p-2 border-b border-gray-200 dark:border-gray-800 flex justify-between items-center w-full bg-white dark:bg-gray-900">
          <button
            type="button"
            onClick={() => setMobileDrawerOpen(true)}
            aria-label="Open conversation history drawer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            <span>Conversations</span>
          </button>

          <button
            type="button"
            onClick={handleCreateNewSession}
            className="px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            + New
          </button>
        </div>

        {/* Sessions Sidebar (Desktop & Mobile Drawer) */}
        <aside
          aria-label="Conversations sidebar"
          className={`fixed inset-y-0 left-0 z-40 w-72 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col transform transition-transform duration-200 ease-in-out lg:static lg:translate-x-0 ${
            mobileDrawerOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <div className="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
            <h2 className="text-sm font-bold text-gray-900 dark:text-white">Conversations</h2>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCreateNewSession}
                className="px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                + New
              </button>
              {mobileDrawerOpen && (
                <button
                  type="button"
                  onClick={() => setMobileDrawerOpen(false)}
                  aria-label="Close conversation drawer"
                  className="lg:hidden p-1 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          <nav aria-label="Conversation list" className="flex-1 overflow-y-auto p-2 space-y-1">
            {isLoadingSessions ? (
              <p className="text-xs text-gray-400 p-3">Loading conversations...</p>
            ) : isSessionsError || sessionsError ? (
              <div className="p-3 text-xs space-y-2">
                <p className="text-gray-500 dark:text-gray-400">Couldn't load conversations.</p>
                <button
                  type="button"
                  onClick={() => void refetchSessions()}
                  className="px-2.5 py-1 text-xs font-semibold rounded bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-900/50 hover:bg-blue-100"
                >
                  Retry
                </button>
              </div>
            ) : sessions.length === 0 ? (
              <p className="text-xs text-gray-400 p-3">No conversations yet.</p>
            ) : (
              sessions.map((s) => {
                const isActive = s.session_id === sessionId;
                return (
                  <button
                    key={s.session_id}
                    type="button"
                    onClick={() => {
                      navigate(`/chat/${s.session_id}`);
                      setMobileDrawerOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors flex flex-col ${
                      isActive
                        ? 'bg-blue-50 dark:bg-blue-950/50 text-blue-900 dark:text-blue-100 font-semibold border border-blue-200 dark:border-blue-900/60'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800/60'
                    }`}
                  >
                    <span className="truncate">{s.title || 'New conversation'}</span>
                    <span className="text-[10px] text-gray-400 mt-0.5">
                      {new Date(s.updated_at).toLocaleDateString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </button>
                );
              })
            )}
          </nav>
        </aside>

        {/* Main Conversation Panel */}
        <main className="flex-1 flex flex-col h-[calc(100vh-4rem)] overflow-hidden">
          {/* Messages Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
            {/* Loading guard: while a session URL is set but data hasn't arrived yet */}
            {sessionId && isLoadingSession ? (
              <div className="flex-1 flex items-center justify-center p-12">
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  Loading conversation…
                </span>
              </div>
            ) : (
              <>
                {/* Empty state: No documents uploaded yet */}
                {!isLoadingDocs && !hasDocuments && (
                  <div
                    role="status"
                    className="max-w-lg mx-auto text-center my-12 p-8 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm space-y-4"
                  >
                    <div className="w-12 h-12 mx-auto rounded-full bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 flex items-center justify-center text-xl">
                      📄
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                        {hasProcessingDocs
                          ? 'Your document is still being processed. You can ask questions when it is ready.'
                          : hasAllFailedDocs
                            ? 'Your documents could not be processed.'
                            : 'Upload a document first'}
                      </h3>
                      {documents.length === 0 && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          To ask questions and receive cited answers, please upload at least one document.
                        </p>
                      )}
                    </div>
                    <Link
                      to="/documents"
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      Go to Documents
                    </Link>
                  </div>
                )}

            {/* Empty state: Session with no messages — Starter Example Questions */}
            {hasDocuments && showStarterExamples && (
              <div className="max-w-xl mx-auto my-12 text-center space-y-4">
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Ask a question about your uploaded documents
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Or select an example question below:
                </p>
                <div className="space-y-2 text-left">
                  {EXAMPLE_QUESTIONS.map((example, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => handleExampleClick(example)}
                      className="w-full p-3 text-xs bg-white dark:bg-gray-900 hover:bg-blue-50/50 dark:hover:bg-blue-950/30 border border-gray-200 dark:border-gray-800 rounded-xl text-gray-800 dark:text-gray-200 transition-colors flex items-center justify-between group focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <span>{example}</span>
                      <span className="text-blue-600 dark:text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity ml-2">
                        Fill ↗
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Saved Conversation Messages */}
            {messages.map((msg, idx) => {
              if (msg.role === 'user') {
                return (
                  <div key={msg.message_id} className="flex justify-end">
                    <div className="max-w-2xl bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm shadow-sm whitespace-pre-wrap">
                      {msg.content}
                    </div>
                  </div>
                );
              }

              const isLastAssistant =
                idx === messages.map((m) => m.role).lastIndexOf('assistant');

              // Find the nearest previous message with role 'user'
              const priorUserMessage = messages
                .slice(0, idx)
                .reverse()
                .find((m) => m.role === 'user');
              const userQuestionToRetry = priorUserMessage?.content;

              return (
                <div key={msg.message_id} className="max-w-3xl space-y-2">
                  {/* Saved Trace Steps (Collapsed) */}
                  {msg.trace && msg.trace.length > 0 && (
                    <AgentSteps steps={msg.trace} isLive={false} />
                  )}

                  {/* Saved Assistant Answer Card */}
                  <AnswerCard
                    content={msg.content}
                    verificationStatus={msg.verification_status}
                    citations={msg.citations ?? []}
                    messageId={msg.message_id}
                    isLive={false}
                    onRetryQuestion={
                      userQuestionToRetry
                        ? () => void handleSend(userQuestionToRetry)
                        : undefined
                    }
                    messageIdFailed={isLastAssistant ? messageIdFailed : false}
                    onReloadRating={reloadMessageId}
                  />
                </div>
              );
            })}

            {/* Live Streaming Turn */}
            {isStreaming && activeSessionId === sessionId && (
              <div className="max-w-3xl space-y-2">
                {/* Active user query display */}
                {lastSentQuery && (
                  <div className="flex justify-end">
                    <div className="max-w-2xl bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm shadow-sm whitespace-pre-wrap">
                      {lastSentQuery}
                    </div>
                  </div>
                )}

                {/* Live Agent Steps */}
                <AgentSteps steps={steps} isLive={true} startTime={streamStartTime} />

                {/* "Stop waiting" button while research is underway */}
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[11px] text-gray-500 italic">
                    Answers are verified before streaming tokens.
                  </span>
                  <button
                    type="button"
                    onClick={stopWaiting}
                    className="px-2.5 py-1 text-xs font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 rounded-lg border border-rose-200 dark:border-rose-900/50 focus:outline-none focus:ring-2 focus:ring-rose-500"
                  >
                    Stop waiting
                  </button>
                </div>

                {/* Streaming answer text as tokens arrive */}
                {answer && (
                  <AnswerCard
                    content={answer}
                    verificationStatus={verificationStatus}
                    citations={citations}
                    messageId={messageId}
                    isLive={true}
                  />
                )}
              </div>
            )}

            {/* Aborted Notice */}
            {isAborted && !isStreaming && (
              <div
                role="status"
                className="p-3 bg-gray-100 dark:bg-gray-800 rounded-xl text-xs text-gray-600 dark:text-gray-300"
              >
                Stopped waiting. The server will finish processing in the background and your answer will appear in conversation history once saved.
              </div>
            )}

            {/* Connection Lost Error */}
            {isConnectionLost && (
              <div
                role="alert"
                className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-xs text-amber-900 dark:text-amber-200 flex items-center justify-between gap-3"
              >
                <span>{CONNECTION_LOST_MESSAGE}</span>
                <button
                  type="button"
                  onClick={() => void handleSend(lastSentQuery)}
                  className="px-3 py-1 bg-amber-600 hover:bg-amber-700 text-white font-medium rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500"
                >
                  Retry
                </button>
              </div>
            )}

            {/* Pre-stream Errors (503 AGENT_BUSY, 429 RATE_LIMITED, 503 DEPENDENCY_UNAVAILABLE, etc.) */}
            {streamError && (
              <InlineErrorNotice
                error={streamError.error}
                retryAfterSeconds={streamError.retryAfter}
                requestId={streamError.requestId}
                onRetry={() => void handleSend(lastSentQuery)}
                buttonLabel={streamError.status === 0 ? 'Retry' : 'Try again'}
              />
            )}
            </>
            )}
          </div>

          {/* Bottom Question Input Area */}
          <div className="border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void handleSend();
              }}
              className="max-w-3xl mx-auto space-y-2"
            >
              {validationError && (
                <p role="alert" className="text-xs text-rose-600 dark:text-rose-400 font-medium">
                  {validationError}
                </p>
              )}

              <div className="flex items-center gap-2">
                <label htmlFor="chat-query-input" className="sr-only">
                  Ask a question
                </label>
                <input
                  id="chat-query-input"
                  type="text"
                  maxLength={2000}
                  value={queryInput}
                  onChange={(e) => {
                    setQueryInput(e.target.value);
                    if (validationError) setValidationError(null);
                  }}
                  disabled={isStreaming}
                  placeholder={docPlaceholder}
                  className="flex-1 px-4 py-2.5 text-sm rounded-xl border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white dark:focus:bg-gray-900 disabled:opacity-50"
                />

                <button
                  type="submit"
                  disabled={isStreaming || !queryInput.trim() || !hasDocuments}
                  className="px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  {isStreaming ? 'Searching...' : 'Send'}
                </button>
              </div>

              <div className="flex justify-between text-[11px] text-gray-400 px-1">
                <span>Press Enter to send</span>
                <span>{queryInput.length}/2000</span>
              </div>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}

