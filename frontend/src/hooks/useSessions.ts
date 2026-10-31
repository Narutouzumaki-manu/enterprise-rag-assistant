// ─────────────────────────────────────────────────────────────────────────────
// useSessions.ts — Sessions management via TanStack Query.
//
// Rules:
//   - GET /sessions: client sorts by updated_at descending.
//   - title may be null ("New conversation").
//   - 404 on session returns user to new conversation.
// ─────────────────────────────────────────────────────────────────────────────

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, ApiRequestError } from '../api/client';
import type { SessionSummary, SessionDetail } from '../api/types';

export const SESSIONS_QUERY_KEY = ['sessions'];
export const sessionDetailQueryKey = (sessionId: string) => ['sessions', sessionId];

export function useSessions() {
  const queryClient = useQueryClient();

  const sessionsQuery = useQuery<SessionSummary[], ApiRequestError>({
    queryKey: SESSIONS_QUERY_KEY,
    queryFn: async () => {
      const { data } = await apiGet<SessionSummary[]>('/sessions?limit=50');
      // Sort client-side by updated_at descending (contract specifies not to rely on server order)
      return [...data].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    },
  });

  const createSessionMutation = useMutation<SessionSummary, ApiRequestError, void>({
    mutationFn: async () => {
      const { data } = await apiPost<SessionSummary>('/sessions', {});
      return data;
    },
    onSuccess: (newSession) => {
      queryClient.setQueryData<SessionSummary[]>(SESSIONS_QUERY_KEY, (old = []) => [
        newSession,
        ...old.filter((s) => s.session_id !== newSession.session_id),
      ]);
    },
  });

  return {
    sessions: sessionsQuery.data ?? [],
    isLoadingSessions: sessionsQuery.isLoading,
    isSessionsError: sessionsQuery.isError,
    sessionsError: sessionsQuery.error?.apiError ?? null,
    refetchSessions: sessionsQuery.refetch,
    createSession: createSessionMutation.mutateAsync,
    isCreatingSession: createSessionMutation.isPending,
  };
}

export function useSessionDetail(sessionId: string | undefined) {
  const query = useQuery<SessionDetail, ApiRequestError>({
    queryKey: sessionDetailQueryKey(sessionId ?? ''),
    queryFn: async () => {
      if (!sessionId) throw new Error('No session ID');
      const { data } = await apiGet<SessionDetail>(`/sessions/${sessionId}`);
      return data;
    },
    enabled: Boolean(sessionId),
  });

  return {
    session: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error?.apiError ?? null,
    refetch: query.refetch,
  };
}

