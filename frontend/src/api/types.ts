// ─────────────────────────────────────────────────────────────────────────────
// types.ts — single source of truth for every shape exchanged with the backend.
// Mirror the API contract exactly; do not add fields that don't exist there.
// ─────────────────────────────────────────────────────────────────────────────

// ─── Authentication ──────────────────────────────────────────────────────────

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
  /** Always 3600 seconds (1 hour). No refresh endpoint exists. */
  expires_in: number;
}

// ─── Sessions & Messages ─────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant';

export type VerificationStatus =
  | 'verified'
  | 'partially_verified'
  | 'unverified';

export type TraceStepType =
  | 'plan'
  | 'retrieve'
  | 'synthesize'
  | 'fact_check';

export interface Citation {
  chunk_id: string;
  document_id: string;
  /** null when page information is unavailable */
  page_number: number | null;
  /** At most ~200 characters; may start with "…". Show as a quotation preview. */
  text_snippet: string;
  /** null when the original document has been deleted */
  source_file: string | null;
}

export interface TraceStep {
  step_type: TraceStepType;
  content: string;
  metadata: Record<string, unknown>;
}

export interface Message {
  message_id: string;
  role: MessageRole;
  content: string;
  created_at: string; // ISO 8601
  // The following four are null/empty for user messages:
  verification_status: VerificationStatus | null;
  /** Never displayed to the user — only verification_status is shown. */
  confidence: number | null;
  latency_ms: number | null;
  citations: Citation[];
  trace: TraceStep[];
}

export interface SessionSummary {
  session_id: string;
  /** null for brand-new sessions. Show as "New conversation". */
  title: string | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

export interface SessionDetail extends SessionSummary {
  messages: Message[];
}

// ─── Documents ───────────────────────────────────────────────────────────────

export type DocumentStatus =
  | 'queued'
  | 'parsing'
  | 'indexing'
  | 'success'
  | 'partial'
  | 'failed'
  | 'duplicate';

/** Statuses that require the UI to keep polling GET /documents every 2 s. */
export const PROCESSING_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  'queued',
  'parsing',
  'indexing',
]);

export interface Document {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  /** Human-readable reason; present when status === 'failed'. */
  error_message: string | null;
  source_type: string;
  created_at: string; // ISO 8601
  /** Only the uploader may delete the document. */
  uploaded_by_me: boolean;
}

export interface UploadResponse {
  document_id: string;
  filename: string;
  /** 'queued' on first upload (202); 'duplicate' when already present (200). */
  status: 'queued' | 'duplicate';
}

// ─── Feedback ────────────────────────────────────────────────────────────────

export type Rating = 1 | -1;

export interface FeedbackRequest {
  message_id: string;
  rating: Rating;
  /** Optional; max 1000 characters. */
  comment?: string;
}

export interface FeedbackResponse {
  message_id: string;
  rating: Rating;
  comment: string | null;
}

// ─── Health ──────────────────────────────────────────────────────────────────

export type DependencyStatus = 'ok' | 'unavailable' | 'disabled';

export interface HealthResponse {
  status: 'ok' | 'degraded';
  checks: {
    postgres: DependencyStatus;
    redis: DependencyStatus;
    retriever: DependencyStatus;
    agent: DependencyStatus;
  };
}

// ─── API Errors ──────────────────────────────────────────────────────────────

export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'FILE_TOO_LARGE'
  | 'UNSUPPORTED_FILE_TYPE'
  | 'RATE_LIMITED'
  | 'AGENT_BUSY'
  | 'DEPENDENCY_UNAVAILABLE'
  | 'INTERNAL_ERROR';

export interface ApiError {
  /** Human-readable message from the server — show this text to the user. */
  error: string;
  code: ErrorCode;
  /** HTTP status code; 0 for network errors. */
  status: number;
  /** Value of the X-Request-ID response header; may be null on 500 or network errors. */
  requestId: string | null;
  /** Parsed Retry-After header (seconds); null when the header is absent. */
  retryAfter: number | null;
}

// ─── Chat stream events ──────────────────────────────────────────────────────
// These arrive over the SSE stream from POST /chat/stream.

export interface StreamStatusEvent {
  event: 'status';
  step_type: TraceStepType;
  /** Already user-readable; display as-is in the agent steps panel. */
  content: string;
}

export interface StreamSourceEvent {
  event: 'source';
  chunk_id: string;
  document_id: string;
  source_file: string | null;
  page_number: number | null;
  text_snippet: string;
}

export interface StreamTokenEvent {
  event: 'token';
  /** One word plus its trailing space; accumulate to build the full answer. */
  text: string;
}

export interface StreamVerificationEvent {
  event: 'verification';
  status: VerificationStatus;
  /** Do not display this number — show verification_status badge only. */
  confidence: number;
}

export interface StreamDoneEvent {
  event: 'done';
  request_id: string;
  confidence: number;
  latency_ms: number;
  // NOTE: No message_id. After this event, refetch GET /sessions/{id} and
  // take the last assistant message to get the message_id for rating.
}

export interface StreamErrorEvent {
  event: 'error';
  error: string;
  code: ErrorCode;
}

/** Discriminated union of all possible SSE events from the chat stream. */
export type StreamEvent =
  | StreamStatusEvent
  | StreamSourceEvent
  | StreamTokenEvent
  | StreamVerificationEvent
  | StreamDoneEvent
  | StreamErrorEvent;

// ─── Chat stream request ─────────────────────────────────────────────────────

export interface ChatStreamRequest {
  session_id: string;
  /** 1–2000 characters; must not be blank. */
  query: string;
  /** Optional number of passages to retrieve; 1–20. */
  top_k?: number;
}

