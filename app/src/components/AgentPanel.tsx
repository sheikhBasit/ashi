import { useState } from "react";
import {
  Play,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader,
} from "lucide-react";
import { runAgent, dispatchTool } from "../api";
import type { AgentRun, AgentStep } from "../types";

export default function AgentPanel() {
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(10);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    if (!goal.trim() || running) return;
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const r = await runAgent(goal.trim(), maxSteps, true);
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function handleConfirm() {
    if (!result?.pending_confirmation) return;
    const { pending_call } = result.pending_confirmation;
    if (!pending_call) return;
    setRunning(true);
    try {
      await dispatchTool(
        pending_call.tool as string,
        pending_call.args as Record<string, unknown>,
      );
      const resumed = await runAgent(result.goal, maxSteps, true);
      setResult(resumed);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  function handleDeny() {
    if (!result) return;
    setResult({ ...result, status: "failed", error: "Action denied by user." });
  }

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        padding: 16,
      }}
    >
      <div
        style={{
          color: "var(--accent)",
          fontWeight: 600,
          fontSize: 11,
          marginBottom: 16,
        }}
      >
        AGENT — AUTONOMOUS TASK RUNNER
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleRun()}
          placeholder="Enter a goal — e.g. 'Research ASHI and write a wiki summary'"
          style={{
            flex: 1,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
            padding: "8px 10px",
            fontSize: 13,
            outline: "none",
            fontFamily: "inherit",
          }}
        />
        <input
          type="number"
          value={maxSteps}
          onChange={(e) => setMaxSteps(Number(e.target.value))}
          min={1}
          max={20}
          title="Max steps"
          style={{
            width: 52,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text-muted)",
            padding: "8px 6px",
            fontSize: 12,
            textAlign: "center",
            outline: "none",
          }}
        />
        <button
          onClick={handleRun}
          disabled={running || !goal.trim()}
          style={{
            background: "var(--accent)",
            border: "none",
            borderRadius: 4,
            padding: "0 14px",
            cursor: running ? "not-allowed" : "pointer",
            opacity: running ? 0.5 : 1,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
          }}
        >
          {running ? <Loader size={13} /> : <Play size={13} />}
          {running ? "Running…" : "Run"}
        </button>
      </div>

      {error && (
        <div
          style={{
            background: "#2a1515",
            border: "1px solid #f87171",
            borderRadius: 6,
            padding: "10px 12px",
            color: "#f87171",
            fontSize: 12,
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {result && (
        <div style={{ flex: 1, overflowY: "auto" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
              padding: "8px 10px",
              background: "var(--surface2)",
              borderRadius: 6,
              border: "1px solid var(--border)",
            }}
          >
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {result.steps_completed}/{result.steps_total} steps
              {result.tcu_id && (
                <span
                  style={{
                    marginLeft: 8,
                    color: "var(--accent)",
                    fontSize: 10,
                  }}
                >
                  TCU: {result.tcu_id}
                </span>
              )}
            </span>
            <StatusBadge status={result.status} />
          </div>

          {result.status === "awaiting_confirmation" &&
            result.pending_confirmation && (
              <div
                style={{
                  background: "#2a2200",
                  border: "1px solid #fbbf24",
                  borderRadius: 6,
                  padding: "12px 14px",
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    color: "#fbbf24",
                    fontWeight: 600,
                    fontSize: 12,
                    marginBottom: 6,
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  <AlertTriangle size={12} />
                  Confirmation required — irreversible action
                </div>
                <pre
                  style={{
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: "var(--text)",
                    marginBottom: 10,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {JSON.stringify(
                    result.pending_confirmation.pending_call,
                    null,
                    2,
                  )}
                </pre>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={handleConfirm}
                    style={{
                      background: "#fbbf24",
                      border: "none",
                      borderRadius: 4,
                      padding: "5px 12px",
                      cursor: "pointer",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#000",
                    }}
                  >
                    Allow
                  </button>
                  <button
                    onClick={handleDeny}
                    style={{
                      background: "transparent",
                      border: "1px solid var(--border)",
                      borderRadius: 4,
                      padding: "5px 12px",
                      cursor: "pointer",
                      fontSize: 12,
                      color: "var(--text-muted)",
                    }}
                  >
                    Deny
                  </button>
                </div>
              </div>
            )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {result.outputs.map((step, i) => (
              <StepCard key={i} step={step} index={i} />
            ))}
          </div>

          {result.final_output && (
            <div
              style={{
                marginTop: 16,
                padding: "12px 14px",
                background: "var(--surface2)",
                border: "1px solid var(--accent)",
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  color: "var(--accent)",
                  fontWeight: 600,
                  fontSize: 11,
                  marginBottom: 8,
                }}
              >
                FINAL OUTPUT
              </div>
              <pre
                style={{
                  fontSize: 12,
                  color: "var(--text)",
                  whiteSpace: "pre-wrap",
                  margin: 0,
                  lineHeight: 1.6,
                }}
              >
                {result.final_output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: AgentRun["status"] }) {
  const config: Record<string, { color: string; label: string }> = {
    done: { color: "var(--green)", label: "Done" },
    failed: { color: "#f87171", label: "Failed" },
    awaiting_confirmation: { color: "#fbbf24", label: "Waiting for approval" },
    budget_exceeded: { color: "var(--text-muted)", label: "Budget exceeded" },
  };
  const { color, label } = config[status] ?? {
    color: "var(--text-muted)",
    label: status,
  };
  return <span style={{ fontSize: 11, color, fontWeight: 600 }}>{label}</span>;
}

function StepCard({ step, index }: { step: AgentStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = step.success ? CheckCircle : XCircle;
  const iconColor = step.success ? "var(--green)" : "#f87171";

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      style={{
        cursor: "pointer",
        background: "var(--surface2)",
        border: "1px solid var(--border)",
        borderRadius: 6,
        padding: "10px 12px",
        userSelect: "none",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={13} color={iconColor} />
        <span
          style={{ fontSize: 11, color: "var(--text-muted)", minWidth: 20 }}
        >
          {index + 1}.
        </span>
        <span style={{ flex: 1, fontSize: 12, color: "var(--text)" }}>
          {step.step}
        </span>
        {step.tool_used && (
          <span
            style={{
              fontSize: 10,
              color: "var(--accent)",
              fontFamily: "monospace",
            }}
          >
            {step.tool_used}
          </span>
        )}
      </div>
      {expanded && (step.output ?? step.error) && (
        <pre
          style={{
            marginTop: 8,
            fontSize: 11,
            color: step.success ? "var(--text-muted)" : "#f87171",
            whiteSpace: "pre-wrap",
            fontFamily: "monospace",
            borderTop: "1px solid var(--border)",
            paddingTop: 8,
            margin: 0,
          }}
        >
          {step.output ?? step.error}
        </pre>
      )}
    </div>
  );
}
