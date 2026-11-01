# Enterprise RAG Assistant — Frontend

The Enterprise RAG Assistant frontend is a single-page React application that provides an intuitive interface for document upload, ingestion tracking, and conversational retrieval-augmented generation (RAG). It enables users to authenticate, manage documents, inspect multi-step agent reasoning, and query knowledge bases with citations, source inspection, and trust indicators. The frontend communicates with a FastAPI backend via RESTful endpoints and Server-Sent Events (SSE) for low-latency streaming answers.

## Tech Stack

- **Framework**: React 18 with TypeScript 5
- **Build Tool & Dev Server**: Vite 5
- **Styling**: Tailwind CSS 3 with PostCSS and Autoprefixer
- **Routing**: React Router 6
- **Server State & Data Fetching**: TanStack React Query 5
- **Testing**: Vitest 2, `@testing-library/react`, `@testing-library/jest-dom`, and `vitest-axe`

---

## Prerequisites

- **Node.js**: Node.js 20 LTS (Active LTS). Install via the [nodejs.org](https://nodejs.org/) installer or Windows Package Manager:
  ```powershell
  winget install OpenJS.NodeJS.LTS
  ```
  *Note: Restart your terminal or VS Code after installing Node.js to update the `PATH` environment variable.*
- **Windows PowerShell Execution Policy**: If running npm or vite scripts in PowerShell displays the error `"running scripts is disabled on this system"`, allow local scripts for your current user:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

---

## Package Scripts

All commands should be executed from the `frontend/` directory:

| Script | Command | Purpose |
| :--- | :--- | :--- |
| `npm run dev` | `vite` | Starts the local Vite development server with proxying and HMR. |
| `npm run build` | `tsc && vite build` | Type-checks code with TypeScript and builds the production bundle into `dist/`. |
| `npm run preview` | `vite preview` | Locally serves the production build from `dist/` to verify packaging. |
| `npm test` | `vitest run` | Executes all Vitest test suites once in jsdom. |
| `npm run test:watch` | `vitest` | Starts the Vitest test runner in interactive watch mode. |
| `npm run test:coverage`| `vitest run --coverage` | Runs all tests and produces code coverage metrics via `@vitest/coverage-v8`. |

---

## Running Against the Mock Backend

The repository includes a standalone mock backend server for development and testing without requiring live external model providers or cloud vector databases.

### 1. Start the Mock Backend (from Repository Root)

The Python backend scripts reside in the top-level `scripts/` directory. You must run them from the **repository root**:

```powershell
# In repository root (e.g., d:\enterprise-rag-assistant):
python -m scripts.create_user
python -m scripts.dev_mock_server
```

The mock backend listens at `http://127.0.0.1:8000`.

> [!WARNING]
> **Common Mistake**: Executing `python -m scripts.dev_mock_server` or `python -m scripts.create_user` from inside the `frontend/` directory will fail with:
> ```text
> No module named 'scripts'
> ```
> Always ensure your terminal working directory is the **repository root** before invoking Python `-m scripts.*` commands.

### 2. Start the Frontend Dev Server

Open a second terminal window, navigate to the `frontend/` directory, and start Vite:

```powershell
cd frontend
npm install
npm run dev
```

Open your browser to:
[http://localhost:5173](http://localhost:5173)

---

## Vite Development Proxy

The Vite dev server (`frontend/vite.config.ts`) proxies API requests to the FastAPI backend running at `http://127.0.0.1:8000`.

### Proxied Paths
- `/auth`
- `/documents`
- `/chat`
- `/sessions`
- `/feedback`
- `/health`

### Upload Constraints

- Maximum file size: 25 MB per file.
- Supported formats: PDF, DOCX, and CSV.
- Other file formats and files exceeding the limit are rejected by client-side validation.

### Key Architectural Details
1. **No Cross-Origin Resource Sharing (CORS) in Development**: The backend server does not configure CORS headers for `localhost:5173`. Vite proxies all `/auth`, `/documents`, `/chat`, `/sessions`, `/feedback`, and `/health` requests to `127.0.0.1:8000`, making all network calls appear same-origin to the browser.
2. **SPA HTML Navigation Bypass (`spaBypass`)**: Because frontend client routes share the same path prefixes as backend API endpoints (`/documents`, `/chat`, and `/sessions`), Vite uses a bypass rule:
   ```ts
   bypass: (req) => req.headers.accept?.includes('text/html') ? '/index.html' : undefined
   ```
   When a user refreshes the page, types `http://localhost:5173/chat` in the browser URL bar, or opens a shared link, the browser sends `Accept: text/html`. Vite serves `index.html` to allow React Router to render the appropriate page instead of forwarding the request to the backend. API calls from `fetch` send `Accept: */*` or `application/json` and are proxied to port 8000.
3. **Unbuffered Server-Sent Events (SSE)**: The streaming endpoint `/chat/stream` requires immediate event delivery. Vite's underlying proxy engine (`http-proxy`) streams HTTP response bodies by default without buffering chunks, ensuring reasoning steps, token deltas, and verification events reach the browser immediately as emitted by the server.

---

## Project Directory Structure

```text
frontend/
├── index.html                   # HTML entry point with dark-mode script
├── package.json                 # Project dependencies, scripts, and metadata
├── postcss.config.js            # PostCSS configuration for Tailwind CSS
├── tailwind.config.ts           # Tailwind CSS configuration and themes
├── tsconfig.json                # TypeScript compiler configuration for app
├── tsconfig.node.json           # TypeScript configuration for Vite config
├── vite.config.ts               # Vite server, dev proxy, and test setup
├── dist/                        # Production build output (generated)
├── src/
│   ├── App.tsx                  # Root component, router routes, and providers
│   ├── constants.ts             # Application constants and error messages
│   ├── index.css                # Global styles, Tailwind directives, dark mode rules
│   ├── main.tsx                 # React entry point mounting to #root DOM node
│   ├── api/
│   │   ├── client.ts            # Typed HTTP client with 401 retry & token refresh
│   │   ├── sse.ts               # EventSource/Fetch-based SSE stream consumer
│   │   ├── streamAbort.ts       # SSE stream abort and cancellation controller
│   │   ├── tokenStore.ts        # In-memory authentication token storage
│   │   ├── types.ts             # TypeScript interfaces mirroring API contracts
│   │   └── upload.ts            # Multipart file upload handler with validation
│   ├── components/
│   │   ├── AgentSteps.tsx       # Live and completed agent reasoning steps display
│   │   ├── AnswerCard.tsx       # Answer card: plain text, trust badge, citations, rating, refusal and retry
│   │   ├── CitationCard.tsx     # Citation pills linking to referenced document chunks
│   │   ├── DocumentRow.tsx      # Document status, polling indicators, and delete button
│   │   ├── ErrorState.tsx       # Full-page and inline error state banners
│   │   ├── NavBar.tsx           # Top navigation bar and log out (dark mode follows the OS; no toggle)
│   │   ├── ProtectedRoute.tsx   # Route guard enforcing active user session
│   │   ├── RatingButtons.tsx    # Upvote/downvote answer rating submission controls
│   │   ├── SkipLink.tsx         # Skip link jumping to #main-content
│   │   ├── TrustBadge.tsx       # Answer verification status indicator badge
│   │   └── UploadArea.tsx       # Drag-and-drop file upload dropzone with validation
│   ├── hooks/
│   │   ├── useAuth.tsx          # Authentication provider and credential state hook
│   │   ├── useChatStream.ts     # Chat streaming lifecycle, token accumulator, steps hook
│   │   ├── useDocuments.ts      # Document queries, mutations, and 2-second polling while processing
│   │   └── useSessions.ts       # Conversation session queries and deletion hook
│   ├── pages/
│   │   ├── Chat.tsx             # Interactive conversational chat interface
│   │   ├── Documents.tsx        # Document management and ingestion dashboard
│   │   └── Login.tsx            # User login and authentication page
│   └── test/
│       ├── a11y.test.tsx        # Accessibility, axe audits, and mobile drawer tests
│       ├── auth.test.tsx        # Authentication provider and session tests
│       ├── chat.test.tsx        # Chat interface, stream handling, and error tests
│       ├── client.test.ts       # API client, 401 handling, and token refresh tests
│       ├── documentRow.test.tsx # Document table row and status badge tests
│       ├── messageIdRefetch.test.tsx # Assistant message ID refetching tests
│       ├── setup.ts             # Vitest test setup, matchers, and canvas mocks
│       ├── sse.test.ts          # SSE parser and event stream consumer tests
│       └── upload.test.ts       # Client-side file validation and upload tests
```

---

## Testing Guide

### Running Tests
Execute the unit and integration test suite:
```powershell
npm test
```
To run tests with a progress dot reporter:
```powershell
npx vitest run --reporter=dot
```

### Verified Test Counts by File
All 110 tests across 8 test suites pass cleanly:
- `src/test/sse.test.ts`: **15 tests** (SSE event parsing, chunk splitting, stream closure)
- `src/test/client.test.ts`: **21 tests** (API client methods, auth headers, 401 token refresh)
- `src/test/upload.test.ts`: **9 tests** (file size limit, MIME/extension validation, formData)
- `src/test/auth.test.tsx`: **5 tests** (login flow, token storage, logout, expired session redirect)
- `src/test/documentRow.test.tsx`: **5 tests** (status tags, date formatting, delete confirmation)
- `src/test/messageIdRefetch.test.tsx`: **4 tests** (session message ID refetching, retry handling)
- `src/test/chat.test.tsx`: **28 tests** (streaming state, 429 busy retry, 503 error notices, session switching)
- `src/test/a11y.test.tsx`: **23 tests** (vitest-axe automated checks, mobile drawer focus trap/inert, aria announcements, safe redirects)

**Total: 110 tests passing.**

### What Vitest / jsdom Tests DO NOT Prove
- **Visual Layout & Viewport Geometry**: jsdom does not calculate layout bounding boxes, CSS flex wrapping, text wrapping, dynamic viewport heights (`dvh`), or horizontal scrollbar emergence at 360 px width. Physical responsiveness must be verified in a real browser.
- **Color Contrast Ratios**: jsdom does not evaluate rendered pixel colors or computed CSS background-to-text contrast ratios. Automated axe scans in jsdom skip contrast verification; color contrast must be audited with browser developer tools or Lighthouse.
- **Backend Model Behavior**: Mock fetch calls verify frontend request construction, token storage, and event handling, but do not validate live FastAPI database queries, external LLM generation, or vector index similarity searches.

---

## Troubleshooting Common Issues

### 1. Port 5173 in Use
If port 5173 is already occupied by another process, Vite will attempt to run on the next available port (e.g., 5174). If you require port 5173, locate and terminate the process holding the port:
```powershell
Get-NetTCPConnection -LocalPort 5173 | Format-Table OwningProcess, State
Stop-Process -Id <OwningProcessId> -Force
```

### 2. Port 8000 in Use
If the FastAPI backend cannot bind to port 8000 because another service or previous mock instance is active:
```powershell
Get-NetTCPConnection -LocalPort 8000 | Format-Table OwningProcess, State
Stop-Process -Id <OwningProcessId> -Force
```

### 3. PowerShell Script Execution Disabled
If running `npm run dev` or `npx` produces `File ... cannot be loaded because running scripts is disabled on this system`:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 4. "No module named 'scripts'"
When starting the mock server, if Python outputs `ModuleNotFoundError: No module named 'scripts'`, your working directory is incorrect. Navigate up to the repository root directory (where the `scripts/` folder is located) before running `python -m scripts.dev_mock_server`.

---

## Honest "Not Built Yet" List

The following capabilities are deliberately not yet implemented in the current application state:
1. **Real Multi-turn Streaming Agent**: The mock server produces simulated reasoning steps and token chunks based on pre-scripted patterns rather than a live multi-turn LangGraph/orchestration agent.
2. **Real Document Parser & Vector Store**: The current mock backend stubs document processing states and retrieval chunks rather than parsing PDFs/DOCX with Unstructured or indexing embeddings into pgvector/Pinecone.
3. **OAuth / SSO Authentication**: Only standard email and password authentication is supported. Social login, Google Workspace OAuth, and SAML/Enterprise SSO providers are not yet integrated.
4. **Mobile Drawer Gesture Swipe**: The mobile conversation drawer opens and closes via button taps and overlay clicks. Touch drag/swipe gestures are not implemented.
5. **End-to-End Browser Tests in CI**: Test suites run in Vitest under headless jsdom. An end-to-end browser testing pipeline (Playwright or Cypress) running against live browsers in CI is not yet configured.
6. **Nginx Reverse Proxy**: Production Nginx configuration is not yet implemented.
7. **Docker Frontend Deployment**: Frontend Docker deployment is not yet configured.
8. **Continuous Integration (CI)**: Frontend CI pipeline is not yet configured.
