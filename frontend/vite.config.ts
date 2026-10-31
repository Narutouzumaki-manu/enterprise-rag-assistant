import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const BACKEND = 'http://127.0.0.1:8000';

// The frontend has pages at /documents, /chat and /sessions, and the backend
// has API routes with the same names. When the browser loads one of these
// URLs as a page (address bar, refresh, a shared link), it sends
// "Accept: text/html". In that case we serve the React app (index.html)
// instead of forwarding to the API. The app's own fetch/XHR calls send
// "Accept: */*" or "application/json", so they still reach the backend.
const spaBypass = (req: { headers: { accept?: string } }): string | undefined => {
  if (req.headers.accept?.includes('text/html')) {
    return '/index.html';
  }
  return undefined;
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    proxy: {
      // All paths forwarded to the FastAPI backend at 127.0.0.1:8000.
      // The backend has no CORS configuration, so we must not call it
      // cross-origin; the proxy is the only correct way in development.
      //
      // http-proxy (used internally by Vite) streams response bodies by
      // default, so the SSE endpoint /chat/stream is NOT buffered and
      // events arrive at the browser as soon as the server emits them.
      // (To be confirmed in Phase C by watching the events arrive one by one.)

      // No frontend page uses these paths, so no bypass is needed.
      '/auth':     { target: BACKEND, changeOrigin: true },
      '/feedback': { target: BACKEND, changeOrigin: true },
      '/health':   { target: BACKEND, changeOrigin: true },

      // Frontend pages share these names with API routes, so page loads
      // (Accept: text/html) must be served by the React app.
      '/sessions':  { target: BACKEND, changeOrigin: true, bypass: spaBypass },
      '/documents': { target: BACKEND, changeOrigin: true, bypass: spaBypass },
      '/chat':      { target: BACKEND, changeOrigin: true, bypass: spaBypass },
    },
  },

  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});