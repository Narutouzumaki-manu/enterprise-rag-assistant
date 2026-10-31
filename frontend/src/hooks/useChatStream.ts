// ─────────────────────────────────────────────────────────────────────────────
// useChatStream.ts — Streaming hook using fetch + ReadableStream + parseSSEStream.
//
// Rules:
//   - POST /chat/stream with Authorization header. Never EventSource.
//   - Uses parseSSEStream from api/sse.ts.
//   - Registers AbortController in streamAbort.ts.
//   - Exactly one of 'done' or 'error' ends stream. If neither -> "connection_lost".
//   - "Stop waiting" aborts the fetch; answer is still saved on server.
//   - After 'done', refetches GET /sessions/{id} to get the assistant message_id.
//   - 503 AGENT_BUSY & 429 pre-stream errors returned for inline display.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useCallback, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getAuthHeaders, apiGet, handleUnauthorizedInStream } from '../api/client';
import { parseSSEStream, type SSETermination } from '../api/sse';
import { registerStreamAbortController } from '../api/streamAbort';
import { sessionDetailQueryKey, SESSIONS_QUERY_KEY } from './useSessions';
import { CONNECTION_LOST_MESSAGE } from '../constants';
import type {
  Citation,
  VerificationStatus,
  StreamEvent,
  SessionDetail,
  ErrorCode,
} from '../api/types';

export interface PreStreamError {
  error: string;
  code: ErrorCode;
  status: number;
  retryAfter: number | null;
  requestId: string | null;
}

export function useChatStream() {
  const queryClient = useQueryClient();

  const [isStreaming, setIsStreaming] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [steps, setSteps] = useState<Array<{ step_type: string; content: string }>>([]);
  const [answer, setAnswer] = useState('');
  const [citations, setCitations] = useState<Citation[]>([]);
  const [verificationStatus, setVerificationStatus] = useState<VerificationStatus | null>(null);
  const [streamStartTime, setStreamStartTime] = useState<number | null>(null);
  const [messageId, setMessageId] = useState<string | null>(null);
  const [messageIdFailed, setMessageIdFailed] = useState(false);

  // Errors & Terminations
  const [streamError, setStreamError] = useState<PreStreamError | null>(null);
  const [isConnectionLost, setIsConnectionLost] = useState(false);
  const [isAborted, setIsAborted] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const runIdRef = useRef(0);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  const resetStream = useCallback(() => {
    setIsStreaming(false);
    setActiveSessionId(null);
    activeSessionIdRef.current = null;
    setSteps([]);
    setAnswer('');
    setCitations([]);
    setVerificationStatus(null);
    setStreamStartTime(null);
    setMessageId(null);
    setMessageIdFailed(false);
    setStreamError(null);
    setIsConnectionLost(false);
    setIsAborted(false);
  }, []);

  const fetchSessionMessageId = useCallback(
    async (sessId: string): Promise<string | null> => {
      const { data: updatedSession } = await apiGet<SessionDetail>(`/sessions/${sessId}`);
      queryClient.setQueryData(sessionDetailQueryKey(sessId), updatedSession);
      void queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY });

      const assistantMsgs = updatedSession.messages.filter((m) => m.role === 'assistant');
      if (assistantMsgs.length > 0) {
        return assistantMsgs[assistantMsgs.length - 1].message_id;
      }
      return null;
    },
    [queryClient],
  );

  const reloadMessageId = useCallback(async () => {
    const sessId = activeSessionIdRef.current;
    if (!sessId) return;
    try {
      const id = await fetchSessionMessageId(sessId);
      if (isMountedRef.current) {
        if (id) {
          setMessageId(id);
          setMessageIdFailed(false);
        } else {
          setMessageIdFailed(true);
        }
      }
    } catch {
      if (isMountedRef.current) {
        setMessageIdFailed(true);
      }
    }
  }, [fetchSessionMessageId]);

  const stopWaiting = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      setIsAborted(true);
    }
  }, []);

  const sendQuery = useCallback(
    async (sessionId: string, query: string, topK?: number): Promise<boolean> => {
      // Reset state for new query
      resetStream();
      setIsStreaming(true);
      setStreamStartTime(Date.now());
      activeSessionIdRef.current = sessionId;
      setActiveSessionId(sessionId);

      const currentRunId = ++runIdRef.current;
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const unregister = registerStreamAbortController(controller);

      const isCurrentRun = () =>
        isMountedRef.current &&
        !controller.signal.aborted &&
        abortControllerRef.current === controller &&
        activeSessionIdRef.current === sessionId &&
        runIdRef.current === currentRunId;

      try {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        };

        let response: Response;
        try {
          response = await fetch('/chat/stream', {
            method: 'POST',
            headers,
            body: JSON.stringify({
              session_id: sessionId,
              query,
              ...(topK ? { top_k: topK } : {}),
            }),
            signal: controller.signal,
          });
        } catch (fetchErr) {
          if (controller.signal.aborted) {
            if (
              isMountedRef.current &&
              abortControllerRef.current === controller &&
              activeSessionIdRef.current === sessionId &&
              runIdRef.current === currentRunId
            ) {
              setIsAborted(true);
            }
            return false;
          }
          // Server unreachable or network error
          if (isCurrentRun()) {
            setStreamError({
              error: CONNECTION_LOST_MESSAGE,
              code: 'INTERNAL_ERROR',
              status: 0,
              retryAfter: null,
              requestId: null,
            });
          }
          return false;
        }

        // Check for pre-stream HTTP errors (422, 404, 503 AGENT_BUSY, 429, etc.)
        if (!response.ok) {
          if (!isCurrentRun()) return false;
          const requestId = response.headers.get('X-Request-ID');
          const retryHeader = response.headers.get('Retry-After');
          const retryAfter = retryHeader ? parseInt(retryHeader, 10) : null;

          let body: { error: string; code: ErrorCode } = {
            error: 'An unexpected error occurred.',
            code: 'INTERNAL_ERROR',
          };
          try {
            body = (await response.json()) as { error: string; code: ErrorCode };
          } catch {
            // Non-JSON error body (e.g. dev proxy connection error when backend is stopped)
            body = {
              error: CONNECTION_LOST_MESSAGE,
              code: 'INTERNAL_ERROR',
            };
          }

          if (response.status === 401) {
            handleUnauthorizedInStream();
            return false;
          }

          if (isCurrentRun()) {
            setStreamError({
              error: body.error,
              code: body.code,
              status: response.status,
              retryAfter: Number.isFinite(retryAfter) ? retryAfter : null,
              requestId,
            });
          }
          return false;
        }

        if (!response.body) {
          if (isCurrentRun()) {
            setIsConnectionLost(true);
          }
          return false;
        }

        // Stream reader loop using existing parseSSEStream
        const termination: SSETermination = await parseSSEStream(
          response.body,
          (event: StreamEvent) => {
            if (!isCurrentRun()) return;
            switch (event.event) {
              case 'status':
                setSteps((prev) => [
                  ...prev,
                  { step_type: event.step_type, content: event.content },
                ]);
                break;
              case 'source':
                setCitations((prev) => [
                  ...prev,
                  {
                    chunk_id: event.chunk_id,
                    document_id: event.document_id,
                    source_file: event.source_file,
                    page_number: event.page_number,
                    text_snippet: event.text_snippet,
                  },
                ]);
                break;
              case 'token':
                setAnswer((prev) => prev + event.text);
                break;
              case 'verification':
                setVerificationStatus(event.status);
                // Do not store or display event.confidence
                break;
              case 'done':
                // Successfully completed
                break;
              case 'error':
                setStreamError({
                  error: event.error,
                  code: event.code,
                  status: 500,
                  retryAfter: null,
                  requestId: null,
                });
                break;
            }
          },
          controller.signal,
        );

        if (termination === 'aborted') {
          if (
            isMountedRef.current &&
            abortControllerRef.current === controller &&
            activeSessionIdRef.current === sessionId &&
            runIdRef.current === currentRunId
          ) {
            setIsAborted(true);
          }
          return false;
        }

        if (!isCurrentRun()) {
          return false;
        }

        if (termination === 'connection_lost') {
          setIsConnectionLost(true);
          return false;
        }

        if (termination === 'error') {
          return false;
        }

        // Refetch session to get the assistant message_id for rating
        if (termination === 'done') {
          let resolvedId: string | null = null;
          try {
            resolvedId = await fetchSessionMessageId(sessionId);
          } catch {
            // If GET /sessions/{id} fails after done, retry it ONCE after about 1.5 seconds
            try {
              await new Promise((resolve) => setTimeout(resolve, 1500));
              if (!isCurrentRun()) {
                return false;
              }
              resolvedId = await fetchSessionMessageId(sessionId);
            } catch {
              if (isCurrentRun()) {
                setMessageIdFailed(true);
              }
            }
          }

          if (isCurrentRun()) {
            if (resolvedId) {
              setMessageId(resolvedId);
              setMessageIdFailed(false);
            } else {
              setMessageIdFailed(true);
            }
          }
          return true;
        }

        return false;
      } finally {
        unregister();
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [fetchSessionMessageId, resetStream],
  );

  return {
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
  };
}

