export interface ChatResponse {
  request_id: string;
  answer: string | null;
  status: "completed" | "from_cache" | "queued" | "failed";
  from_cache: boolean;
  fused: boolean;
  latency_ms: number;
  message: string | null;
  error: string | null;
  queue_position: number | null;
}

export interface Candidate {
  label: string;
  text: string;
  score_pct: number;
  is_winner: boolean;
  fused: boolean;
  model_id: string | null;
  provider: string | null;
}

export interface CandidatesResponse {
  request_id: string;
  revealed: boolean;
  candidates: Candidate[];
}

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ModelCard {
  model_id: string;
  provider: string;
  status: string;
  success_rate_24h: number | null;
  latency_p95_ms: number | null;
  invocations_24h: number;
}

export interface AdminMetrics {
  window_hours: number;
  total_requests: number;
  success_rate: number | null;
  cache_hit_rate: number | null;
  latency_p95_ms: number | null;
  fused_answers: number;
  models: ModelCard[];
}

export interface AdminModel {
  id: string;
  provider: string;
  tier: string;
  routing_weight: number;
  context_window: number | null;
  status: string;
  capabilities: Record<string, unknown>;
  requires_verification: boolean;
  credentials_required: boolean;
  last_health_check_at: string | null;
}

export interface Alert {
  severity: "critical" | "warning" | "info";
  model_id: string | null;
  message: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: string;
  expires_in_minutes: number;
}
