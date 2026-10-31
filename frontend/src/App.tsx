// ─────────────────────────────────────────────────────────────────────────────
// App.tsx — Top-level router and context providers.
// ─────────────────────────────────────────────────────────────────────────────

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './hooks/useAuth';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Login } from './pages/Login';
import { Documents } from './pages/Documents';

// Single QueryClient instance for the app
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false, // Don't retry blindly on errors per the contract
      refetchOnWindowFocus: false,
    },
  },
});

// Temporary placeholder for Chat until Phase C
function ChatPlaceholder() {
  return (
    <div className="p-8 text-center text-gray-500">
      Chat page will be built in Phase C.
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/documents"
              element={
                <ProtectedRoute>
                  <Documents />
                </ProtectedRoute>
              }
            />
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <ChatPlaceholder />
                </ProtectedRoute>
              }
            />
            <Route
              path="/chat/:sessionId"
              element={
                <ProtectedRoute>
                  <ChatPlaceholder />
                </ProtectedRoute>
              }
            />
            {/* Default redirect to /chat */}
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
