// ─────────────────────────────────────────────────────────────────────────────
// useDocuments.ts — TanStack Query hook for documents list & delete mutation.
// Automatically polls every 2 seconds while any document is processing.
// ─────────────────────────────────────────────────────────────────────────────

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiDelete, ApiRequestError } from '../api/client';
import { PROCESSING_STATUSES, type Document } from '../api/types';

export const DOCUMENTS_QUERY_KEY = ['documents'];

export function useDocuments() {
  const queryClient = useQueryClient();
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const query = useQuery<Document[], ApiRequestError>({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: async () => {
      const { data } = await apiGet<Document[]>('/documents');
      return data;
    },
    // Poll every 2 seconds while any document is queued, parsing, or indexing.
    // Stops polling automatically as soon as all documents reach a final status.
    refetchInterval: (query) => {
      const docs = query.state.data;
      if (!docs || docs.length === 0) return false;
      const hasPending = docs.some((doc) => PROCESSING_STATUSES.has(doc.status));
      return hasPending ? 2000 : false;
    },
  });

  const deleteMutation = useMutation<void, ApiRequestError, string>({
    mutationFn: async (documentId: string) => {
      setDeleteError(null);
      await apiDelete(`/documents/${documentId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY });
    },
    onError: (err) => {
      setDeleteError(err.apiError.error);
    },
  });

  return {
    documents: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error?.apiError ?? null,
    refetch: query.refetch,
    deleteDocument: deleteMutation.mutateAsync,
    isDeleting: deleteMutation.isPending,
    deleteError,
    clearDeleteError: () => setDeleteError(null),
  };
}

