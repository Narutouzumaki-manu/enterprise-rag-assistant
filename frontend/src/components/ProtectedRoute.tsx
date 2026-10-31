// ─────────────────────────────────────────────────────────────────────────────
// ProtectedRoute.tsx — Guards authenticated pages.
// Redirects unauthenticated users to /login remembering where they were.
// ─────────────────────────────────────────────────────────────────────────────

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

interface ProtectedRouteProps {
  children: React.ReactElement;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    const from = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?from=${from}`} replace />;
  }

  return children;
}

