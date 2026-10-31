import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { renderHook, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from '../hooks/useAuth';
import { setToken, getToken, clearToken } from '../api/tokenStore';
import * as clientModule from '../api/client';
import * as streamAbortModule from '../api/streamAbort';

describe('useAuth & Authentication lifecycle', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    clearToken();
    queryClient = new QueryClient();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearToken();
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>{children}</AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );

  it('initializes with unauthenticated state when no token in storage', () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBeNull();
  });

  it('initializes with authenticated state when token is present in storage', () => {
    setToken('existing-token-abc');
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.token).toBe('existing-token-abc');
  });

  it('successful login stores token and updates authenticated state', async () => {
    vi.spyOn(clientModule, 'apiPost').mockResolvedValueOnce({
      data: {
        access_token: 'new-login-token',
        token_type: 'bearer',
        expires_in: 3600,
      },
      requestId: 'req-login',
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login({ email: 'user@example.com', password: 'secret' });
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.token).toBe('new-login-token');
    expect(getToken()).toBe('new-login-token');
  });

  it('logout clears token, clears queryClient cache, and aborts active streams', () => {
    setToken('active-token');
    const abortSpy = vi.spyOn(streamAbortModule, 'abortAllActiveStreams');
    const clearQuerySpy = vi.spyOn(queryClient, 'clear');

    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.isAuthenticated).toBe(true);

    act(() => {
      result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBeNull();
    expect(getToken()).toBeNull();
    expect(sessionStorage.getItem('rag_token')).toBeNull();
    expect(abortSpy).toHaveBeenCalled();
    expect(clearQuerySpy).toHaveBeenCalled();
  });
});

