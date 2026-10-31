// ─────────────────────────────────────────────────────────────────────────────
// useAuth.tsx — Authentication context, token state, login, and logout.
// ─────────────────────────────────────────────────────────────────────────────

import  {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { getToken, setToken, clearToken } from '../api/tokenStore';
import { apiPost, registerUnauthorizedHandler, ApiRequestError } from '../api/client';
import { abortAllActiveStreams } from '../api/streamAbort';
import type { AuthToken, LoginRequest, ApiError } from '../api/types';

interface AuthContextType {
  token: string | null;
  isAuthenticated: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => void;
  isLoggingIn: boolean;
  loginError: ApiError | null;
  clearLoginError: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tokenState, setTokenState] = useState<string | null>(() => getToken());
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState<ApiError | null>(null);

  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const clearLoginError = useCallback(() => {
    setLoginError(null);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    abortAllActiveStreams();
    queryClient.clear();
    setTokenState(null);
    navigate('/login', { replace: true });
  }, [navigate, queryClient]);

  // Hook global 401 handling into react router and queryClient
  useEffect(() => {
    registerUnauthorizedHandler(() => {
      clearToken();
      abortAllActiveStreams();
      queryClient.clear();
      setTokenState(null);

      const path = window.location.pathname;
      const search = window.location.search;
      const current = path + search;
      const fromParam = encodeURIComponent(current.startsWith('/login') ? '/chat' : current);
      navigate(`/login?from=${fromParam}&expired=1`, { replace: true });
    });
  }, [navigate, queryClient]);

  const login = useCallback(
    async (credentials: LoginRequest): Promise<void> => {
      setIsLoggingIn(true);
      setLoginError(null);
      try {
        const { data } = await apiPost<AuthToken>('/auth/login', credentials);
        setToken(data.access_token);
        setTokenState(data.access_token);
      } catch (err) {
        if (err instanceof ApiRequestError) {
          setLoginError(err.apiError);
        } else {
          setLoginError({
            error: 'Failed to log in. Please check your connection and try again.',
            code: 'INTERNAL_ERROR',
            status: 0,
            requestId: null,
            retryAfter: null,
          });
        }
        throw err;
      } finally {
        setIsLoggingIn(false);
      }
    },
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        token: tokenState,
        isAuthenticated: tokenState !== null,
        login,
        logout,
        isLoggingIn,
        loginError,
        clearLoginError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

