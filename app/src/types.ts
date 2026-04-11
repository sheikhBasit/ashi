export type Panel = "pipeline" | "wiki" | "tasks" | "logs" | "terminal" | "monitor" | "agent";

export interface Skill {
  name: string;
  system: "ollama" | "claude";
  description?: string;
  plugin?: string;
  model_hint?: string;
  ollama_wrapper?: string;
  derived_from?: string;
  invoke: "run_skill" | "claude_session";
}

export interface TCU {
  id: string;
  intent: string;
  status: "pending" | "running" | "done" | "failed";
  created_at: string;
  judge?: { score: number; verdict: string; notes: string };
}

export interface WikiResult {
  file: string;
  path: string;
  score: number;
  snippet: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  skill?: string;
  tokens?: number;
  timestamp: string;
}

export interface SystemStats {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_percent: number;
  swap_used_gb: number;
  swap_total_gb: number;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  cpu_percent: number;
  memory_mb: number;
  status: string;
}

export interface NetworkStats {
  bytes_sent_mb: number;
  bytes_recv_mb: number;
}

export interface ServiceStatus {
  status: "up" | "down";
  latency_ms: number | null;
}

export interface MonitorData {
  system: SystemStats;
  processes: ProcessInfo[];
  network: NetworkStats;
  services: Record<string, ServiceStatus>;
  crons: Array<{ schedule: string; command: string }>;
  timestamp: string;
}

export interface PipelineNode {
  id: string;
  type: "input" | "agent" | "function" | "condition" | "output";
  label: string;
  skill?: string;
  tool?: string;
  model?: "planner" | "executor" | "router";
  position: { x: number; y: number };
}

export interface AgentStep {
  step: string;
  success: boolean;
  tool_used: string;
  output?: string;
  error?: string;
  requires_confirmation?: boolean;
  risk?: string;
  pending_call?: Record<string, unknown>;
}

export interface AgentRun {
  goal: string;
  status: "done" | "failed" | "awaiting_confirmation" | "budget_exceeded";
  steps_completed: number;
  steps_total: number;
  outputs: AgentStep[];
  final_output: string;
  tcu_id: string | null;
  pending_confirmation: {
    step_index: number;
    step: string;
    pending_call: Record<string, unknown> | null;
  } | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}
