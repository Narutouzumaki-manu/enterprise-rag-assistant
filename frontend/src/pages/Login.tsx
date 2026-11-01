// ─────────────────────────────────────────────────────────────────────────────
// Login.tsx — User authentication page.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, type FormEvent } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { SkipLink } from '../components/SkipLink';

export function getSafeRedirect(fromParam: string | null): string {
  if (!fromParam) return '/chat';
  try {
    const decoded = decodeURIComponent(fromParam);
    // Reject any value containing whitespace (\s) or control characters (\u0000-\u001f)
    if (/[\s\u0000-\u001f]/.test(decoded)) {
      return '/chat';
    }
    // Safe redirect: starts with a single "/", contains no "//", no "\", and no ":" before the first "/"
    const firstSlash = decoded.indexOf('/');
    const colon = decoded.indexOf(':');
    if (
      !decoded.startsWith('/') ||
      decoded.startsWith('//') ||
      decoded.includes('//') ||
      decoded.includes('\\') ||
      (colon !== -1 && colon < firstSlash)
    ) {
      return '/chat';
    }
    return decoded;
  } catch {
    return '/chat';
  }
}

export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Sign In - Enterprise RAG Assistant';
  }, []);

  const { login, isLoggingIn, loginError, clearLoginError, isAuthenticated } = useAuth();

  const isExpired = searchParams.get('expired') === '1';
  const from = getSafeRedirect(searchParams.get('from'));

  // If already authenticated, redirect to the target page or /chat
  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  // Handle countdown for rate limits (429) if Retry-After is returned
  const [countdown, setCountdown] = useState<number | null>(null);

  useEffect(() => {
    if (loginError?.retryAfter && loginError.retryAfter > 0) {
      setCountdown(loginError.retryAfter);
      const interval = setInterval(() => {
        setCountdown((prev) => {
          if (prev === null || prev <= 1) {
            clearInterval(interval);
            return null;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [loginError]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password || isLoggingIn || countdown !== null) {
      return;
    }

    try {
      await login({ email: email.trim(), password });
      navigate(from, { replace: true });
    } catch {
      // Error is set in context
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950 px-4 sm:px-6 lg:px-8">
      <SkipLink />
      <main
        id="main-content"
        tabIndex={-1}
        className="max-w-md w-full space-y-8 bg-white dark:bg-gray-900 p-6 sm:p-8 rounded-xl shadow-md border border-gray-200 dark:border-gray-800 outline-none"
      >
        <div>
          <h1 className="text-center text-3xl font-extrabold text-gray-900 dark:text-white">
            Enterprise RAG Assistant
          </h1>
          <p className="mt-2 text-center text-sm text-gray-600 dark:text-gray-400">
            Sign in to access your documents and conversations
          </p>
        </div>

        {isExpired && (
          <div
            role="alert"
            className="rounded-md bg-amber-50 dark:bg-amber-950/40 p-4 border border-amber-200 dark:border-amber-800"
          >
            <p className="text-sm text-amber-800 dark:text-amber-200 font-medium">
              Your session expired. Please log in again.
            </p>
          </div>
        )}

        <form className="mt-8 space-y-6" onSubmit={handleSubmit} noValidate>
          <div className="space-y-4">
            <div>
              <label
                htmlFor="email-address"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Email address
              </label>
              <input
                id="email-address"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (loginError) clearLoginError();
                }}
                disabled={isLoggingIn}
                className="mt-1 appearance-none relative block w-full px-3 py-2.5 min-h-[40px] border border-gray-300 dark:border-gray-700 placeholder-gray-500 dark:placeholder-gray-400 text-gray-900 dark:text-white rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 focus:border-blue-500 dark:bg-gray-800 text-sm disabled:opacity-50"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (loginError) clearLoginError();
                }}
                disabled={isLoggingIn}
                className="mt-1 appearance-none relative block w-full px-3 py-2.5 min-h-[40px] border border-gray-300 dark:border-gray-700 placeholder-gray-500 dark:placeholder-gray-400 text-gray-900 dark:text-white rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 focus:border-blue-500 dark:bg-gray-800 text-sm disabled:opacity-50"
                placeholder="••••••••"
              />
            </div>
          </div>

          {loginError && (
            <div
              role="alert"
              className="rounded-md bg-red-50 dark:bg-red-950/40 p-4 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300 space-y-1"
            >
              <p className="font-medium">{loginError.error}</p>
              {loginError.status === 429 && countdown !== null && (
                <p className="text-xs text-red-600 dark:text-red-400">
                  Too many attempts. You can try again in {countdown}s.
                </p>
              )}
              {loginError.requestId && (
                <p className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                  Request ID: {loginError.requestId}
                </p>
              )}
            </div>
          )}

          <div>
            <button
              type="submit"
              disabled={isLoggingIn || !email.trim() || !password || countdown !== null}
              className="group relative w-full flex justify-center items-center py-2.5 px-4 min-h-[40px] border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 dark:focus-visible:ring-offset-gray-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoggingIn
                ? 'Signing in...'
                : countdown !== null
                  ? `Wait ${countdown}s`
                  : 'Sign in'}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

