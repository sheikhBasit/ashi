import { useState, useRef, useEffect } from "react";
import { Send, Zap } from "lucide-react";
import type { ChatMessage, Skill } from "../types";
import { runSkill, dispatchTool } from "../api";

interface ChatPanelProps {
  skills: Skill[];
}

// Intent → skill routing rules (checked in order, first match wins)
const SKILL_ROUTES: Array<{ patterns: string[]; skill: string }> = [
  { patterns: ["plan", "steps", "how to", "roadmap", "break down", "strategy"], skill: "plan" },
  { patterns: ["write", "code", "implement", "function", "class", "script", "fix bug", "debug code"], skill: "code" },
  { patterns: ["review", "check", "audit", "critique", "feedback", "improve"], skill: "review" },
  { patterns: ["ingest", "add to wiki", "save this", "store", "remember this"], skill: "ingest" },
  { patterns: ["wiki", "update entity", "update knowledge", "add fact"], skill: "wiki-update" },
  { patterns: ["report", "daily", "summary of today", "what did i do"], skill: "daily-report" },
  { patterns: ["search", "find", "what is", "who is", "tell me about", "look up", "research"], skill: "research" },
];

// Tool routes — when to call a tool directly instead of a skill
const TOOL_ROUTES: Array<{ patterns: string[]; tool: string; buildArgs: (q: string) => Record<string, unknown> }> = [
  {
    patterns: ["search wiki", "wiki search", "find in wiki"],
    tool: "search_wiki",
    buildArgs: (q) => ({ query: q, wiki_path: "~/Desktop/SecondBrain/wiki", top_k: 5 }),
  },
  {
    patterns: ["run ", "$ ", "bash ", "shell ", "execute ", "list files", "check disk", "ls ", "pwd", "ps aux", "df ", "du ", "cat ", "grep ", "find "],
    tool: "run_shell",
    buildArgs: (q) => {
      // strip natural language prefix if present
      const cmd = q.replace(/^(run|execute|bash|shell)\s+/i, "").trim();
      return { command: cmd, cwd: "~/Desktop/SecondBrain", timeout: 30 };
    },
  },
];

function routeIntent(text: string, skills: Skill[]): { type: "skill"; name: string } | { type: "tool"; tool: string; buildArgs: (q: string) => Record<string, unknown> } | { type: "time" } {
  const lower = text.toLowerCase();

  // time/date queries
  if (/\b(time|date|today|now|current date|what time|what day)\b/.test(lower)) {
    return { type: "time" };
  }

  // explicit /skill command
  const cmdMatch = text.match(/^\/(\S+)/);
  if (cmdMatch) {
    const name = cmdMatch[1];
    const available = skills.filter(s => s.system === "ollama").map(s => s.name);
    if (available.includes(name)) return { type: "skill", name };
  }

  // tool routes
  for (const route of TOOL_ROUTES) {
    if (route.patterns.some(p => lower.includes(p))) {
      return { type: "tool", tool: route.tool, buildArgs: route.buildArgs };
    }
  }

  // skill routes
  for (const route of SKILL_ROUTES) {
    if (route.patterns.some(p => lower.includes(p))) {
      const available = skills.filter(s => s.system === "ollama").map(s => s.name);
      if (available.includes(route.skill)) return { type: "skill", name: route.skill };
    }
  }

  // default
  return { type: "skill", name: "research" };
}

function nowContext() {
  const now = new Date();
  return {
    date: now.toISOString().slice(0, 10),
    time: now.toLocaleTimeString("en-US", { hour12: false }),
    datetime: now.toISOString(),
    weekday: now.toLocaleDateString("en-US", { weekday: "long" }),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  };
}

export default function ChatPanel({ skills }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "ASHI online. Local brain active.\n\nI auto-route your message to the right skill. Type `/skill <name>` to force a specific skill, or just ask naturally.\n\nAvailable: /plan /code /review /research /ingest /wiki-update /daily-report",
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastRoute, setLastRoute] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");

    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    const tc = nowContext();
    const query = text.replace(/^\/\S+\s*/, "").trim() || text;

    try {
      const route = routeIntent(text, skills);

      if (route.type === "time") {
        // Answer directly without hitting Ollama
        setLastRoute("built-in:time");
        const content = `Current time: **${tc.time}**\nDate: **${tc.date}** (${tc.weekday})\nTimezone: ${tc.timezone}`;
        setMessages((prev) => [...prev, {
          role: "assistant",
          content,
          skill: "built-in",
          timestamp: new Date().toISOString(),
        }]);

      } else if (route.type === "tool") {
        setLastRoute(`tool:${route.tool}`);
        const args = route.buildArgs(query);
        const result = await dispatchTool(route.tool, args);
        // Format shell results nicely
        let content: string;
        if (route.tool === "run_shell" && typeof result === "object" && result !== null) {
          const r = result as { stdout?: string; stderr?: string; exit_code?: number; timed_out?: boolean };
          const parts: string[] = [];
          if (r.stdout?.trim()) parts.push(r.stdout.trim());
          if (r.stderr?.trim()) parts.push(`stderr:\n${r.stderr.trim()}`);
          if (r.timed_out) parts.push("[timed out]");
          else parts.push(`exit ${r.exit_code}`);
          content = parts.join("\n\n");
        } else {
          content = typeof result === "string" ? result : JSON.stringify(result, null, 2);
        }
        setMessages((prev) => [...prev, {
          role: "assistant",
          content,
          skill: route.tool,
          timestamp: new Date().toISOString(),
        }]);

      } else {
        // skill route
        const skillName = route.name;
        setLastRoute(`skill:${skillName}`);

        const context: Record<string, string> = {
          topic: query,
          depth: "brief",
          context: `Current datetime: ${tc.datetime} (${tc.weekday}, ${tc.timezone})`,
          goal: query,
          spec: query,
          existing_code: "",
          language: "python",
          artifact: query,
          criteria: "correctness, clarity",
          source: query,
          label: "chat",
          date: tc.date,
          time: tc.time,
          projects: "ashi",
          intent_entries: query,
          tcu_count: "0",
          entity_name: query.slice(0, 40),
          entity_type: "concept",
          new_facts: "",
          focus: "key facts",
          task: query,
          current_state: "",
        };

        const result = await runSkill(skillName, context);
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: result.output,
          skill: result.skill,
          tokens: result.tokens_used,
          timestamp: new Date().toISOString(),
        }]);
      }
    } catch (err) {
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: `Error: ${String(err)}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div style={{
      width: 340,
      minWidth: 280,
      display: "flex",
      flexDirection: "column",
      borderLeft: "1px solid var(--border)",
      background: "var(--surface)",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 12px",
        borderBottom: "1px solid var(--border)",
        fontSize: 11,
        color: "var(--text-muted)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>CHAT</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {lastRoute && (
            <span style={{ color: "var(--text-muted)", fontSize: 10, fontFamily: "monospace" }}>
              → {lastRoute}
            </span>
          )}
          <Zap size={11} color="var(--green)" />
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div style={{
              fontSize: 10,
              color: "var(--text-muted)",
              marginBottom: 3,
              display: "flex",
              justifyContent: "space-between",
            }}>
              <span>{msg.role === "user" ? "you" : msg.skill ? `ashi/${msg.skill}` : "ashi"}</span>
              {msg.tokens && <span>{msg.tokens} tok</span>}
            </div>
            <div style={{
              background: msg.role === "user" ? "var(--accent-dim)" : "var(--surface2)",
              border: `1px solid ${msg.role === "user" ? "var(--accent)" : "var(--border)"}`,
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 12,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: msg.role === "user" ? "var(--accent)" : "var(--text)",
            }}>
              {msg.content}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ color: "var(--text-muted)", fontSize: 11, padding: "4px 8px" }}>
            routing → {lastRoute || "..."} thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{
        borderTop: "1px solid var(--border)",
        padding: "8px",
        display: "flex",
        gap: 6,
      }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask anything — auto-routed to right skill..."
          rows={2}
          style={{
            flex: 1,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
            padding: "6px 8px",
            fontSize: 12,
            resize: "none",
            outline: "none",
            fontFamily: "inherit",
          }}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          style={{
            background: "var(--accent)",
            border: "none",
            borderRadius: 4,
            padding: "0 10px",
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading ? 0.5 : 1,
            color: "#fff",
          }}
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}
