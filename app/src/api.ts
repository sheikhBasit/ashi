/**
 * Tauri IPC bridge — wraps all backend commands.
 * Falls back to mock data when running in browser (dev without Tauri).
 */
import { invoke } from "@tauri-apps/api/core";
import type { WikiResult, TCU, Skill, MonitorData, AgentRun } from "./types";

const IS_TAURI =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function call<T>(
  cmd: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  if (IS_TAURI) {
    return invoke<T>(cmd, args);
  }
  // browser dev mode — return mocks
  return mockCall<T>(cmd, args);
}

// ---- Commands ----

export async function listSkills(): Promise<Skill[]> {
  const raw = await call<string>("list_skills");
  return JSON.parse(raw);
}

export async function listTCUs(): Promise<TCU[]> {
  const raw = await call<string>("list_tcus");
  return JSON.parse(raw);
}

export async function searchWiki(
  query: string,
  topK = 5,
): Promise<WikiResult[]> {
  const raw = await call<string>("search_wiki", { query, topK });
  return JSON.parse(raw);
}

export async function runSkill(
  skillName: string,
  context: Record<string, string>,
): Promise<{
  output: string;
  model: string;
  tokens_used: number;
  skill: string;
}> {
  const raw = await call<string>("run_skill", {
    skillName,
    contextJson: JSON.stringify(context),
  });
  return JSON.parse(raw);
}

export async function readWikiFile(path: string): Promise<string> {
  return call<string>("read_wiki_file", { path });
}

export async function runShell(
  command: string,
  cwd?: string,
  timeout?: number,
): Promise<{
  stdout: string;
  stderr: string;
  exit_code: number;
  command: string;
  cwd: string;
  timed_out: boolean;
}> {
  const raw = await call<string>("run_shell", { command, cwd, timeout });
  return JSON.parse(raw);
}

export async function getMonitorStats(): Promise<MonitorData> {
  const raw = await call<string>("get_monitor_stats");
  return JSON.parse(raw) as MonitorData;
}

export async function dispatchTool(
  toolName: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const raw = await call<string>("dispatch_tool", {
    toolName,
    argsJson: JSON.stringify(args),
  });
  return JSON.parse(raw);
}

export async function runAgent(
  goal: string,
  maxSteps = 10,
  requireConfirmation = true,
): Promise<AgentRun> {
  const raw = await call<string>("run_agent", {
    goal,
    maxSteps,
    requireConfirmation,
  });
  return JSON.parse(raw);
}

// ---- Mock data for browser dev ----

function mockCall<T>(cmd: string, _args: Record<string, unknown>): T {
  const mocks: Record<string, unknown> = {
    list_skills: JSON.stringify([
      {
        name: "research",
        system: "ollama",
        description: "Research a topic via wiki",
        invoke: "run_skill",
      },
      {
        name: "plan",
        system: "ollama",
        description: "Break goals into steps",
        invoke: "run_skill",
      },
      {
        name: "code",
        system: "ollama",
        description: "Write clean code",
        invoke: "run_skill",
      },
      {
        name: "review",
        system: "ollama",
        description: "Review code or output",
        invoke: "run_skill",
      },
      {
        name: "systematic-debugging",
        system: "claude",
        plugin: "superpowers",
        description: "Root-cause debugging",
        invoke: "claude_session",
        ollama_wrapper: "skills/claude-wrappers/systematic-debugging.md",
      },
      {
        name: "frontend-design",
        system: "claude",
        plugin: "frontend-design",
        description: "Production-grade UI design",
        invoke: "claude_session",
      },
      {
        name: "brainstorming",
        system: "claude",
        plugin: "superpowers",
        description: "Structured brainstorming",
        invoke: "claude_session",
        ollama_wrapper: "skills/claude-wrappers/brainstorming.md",
      },
    ]),
    list_tcus: JSON.stringify([
      {
        id: "mock_001",
        intent: "Research ASHI architecture",
        status: "done",
        created_at: new Date().toISOString(),
        judge: { score: 9, verdict: "pass", notes: "Well done" },
      },
      {
        id: "mock_002",
        intent: "Write wiki update for Phase 1",
        status: "running",
        created_at: new Date().toISOString(),
      },
    ]),
    search_wiki: JSON.stringify([
      {
        file: "ashi.md",
        path: "/wiki/ashi.md",
        score: 4.2,
        snippet:
          "# ASHI\nASHI is a local AI operating system built on Ollama...",
      },
    ]),
    run_skill: JSON.stringify({
      output: "# Research: ASHI\n\nASHI is a local-first AI OS...",
      model: "qwen3:4b-16k",
      tokens_used: 312,
      skill: "research",
    }),
    run_shell: JSON.stringify({
      stdout: "mock output\n",
      stderr: "",
      exit_code: 0,
      command: "echo mock",
      cwd: "/home/basitdev/Desktop/SecondBrain",
      timed_out: false,
    }),
    dispatch_tool: JSON.stringify({ status: "ok", result: "mock result" }),
    get_monitor_stats: JSON.stringify({
      system: {
        cpu_percent: 12.4,
        ram_used_gb: 6.2,
        ram_total_gb: 16.0,
        ram_percent: 38.7,
        disk_used_gb: 142.3,
        disk_total_gb: 512.0,
        disk_percent: 27.8,
        swap_used_gb: 0.1,
        swap_total_gb: 2.0,
      },
      processes: [
        {
          pid: 1234,
          name: "ollama",
          cpu_percent: 4.2,
          memory_mb: 512.0,
          status: "sleeping",
        },
        {
          pid: 5678,
          name: "node",
          cpu_percent: 2.1,
          memory_mb: 210.5,
          status: "sleeping",
        },
        {
          pid: 9012,
          name: "python3",
          cpu_percent: 1.8,
          memory_mb: 88.3,
          status: "sleeping",
        },
        {
          pid: 3456,
          name: "chrome",
          cpu_percent: 1.2,
          memory_mb: 340.0,
          status: "sleeping",
        },
        {
          pid: 7890,
          name: "code",
          cpu_percent: 0.9,
          memory_mb: 275.1,
          status: "sleeping",
        },
      ],
      network: { bytes_sent_mb: 120.5, bytes_recv_mb: 840.2 },
      services: {
        ollama: { status: "up", latency_ms: 0.8 },
        langfuse: { status: "down", latency_ms: null },
        docker: { status: "up", latency_ms: 1.2 },
      },
      crons: [
        {
          schedule: "0 0,12 * * *",
          command: "~/Desktop/SecondBrain/skills/instagram-bot.sh",
        },
        {
          schedule: "0 9 * * 1-5",
          command: "~/Desktop/SecondBrain/skills/linkedin-bot.sh",
        },
        {
          schedule: "0 3 * * *",
          command: "~/Desktop/SecondBrain/skills/ralph-loop.sh",
        },
      ],
      timestamp: new Date().toISOString(),
    }),
    read_wiki_file:
      "# ASHI\n\nASHI is a local-first AI OS built on Ollama.\n\n## Architecture\n\n- **TCU** — atomic task unit\n- **Skills** — Claude-authored prompts\n- **Ralph Loop** — daily self-improvement\n",
    run_agent: JSON.stringify({
      goal: "mock goal",
      status: "done",
      steps_completed: 2,
      steps_total: 2,
      outputs: [
        {
          step: "Search wiki",
          success: true,
          tool_used: "search_wiki",
          output: "Found ASHI docs",
        },
        {
          step: "Summarize findings",
          success: true,
          tool_used: "run_skill",
          output: "ASHI is a local AI OS",
        },
      ],
      final_output: "Goal completed successfully.",
      tcu_id: "mock_agent_001",
      pending_confirmation: null,
      error: null,
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
    } as AgentRun),
  };
  return (mocks[cmd] ?? null) as T;
}
