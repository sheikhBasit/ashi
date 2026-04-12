import { RefreshCw } from "lucide-react";
import type { TCU } from "../types";

const STATUS_COLOR: Record<string, string> = {
  pending: "var(--yellow)",
  running: "var(--accent)",
  done:    "var(--green)",
  failed:  "var(--red)",
};

interface TasksViewProps {
  tcus: TCU[];
  onRefresh: () => void;
}

export default function TasksView({ tcus, onRefresh }: TasksViewProps) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        flexShrink: 0,
      }}>
        <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11 }}>TASKS</span>
        <span style={{ color: "var(--text-muted)", fontSize: 11 }}>{tcus.length} total</span>
        <button
          onClick={onRefresh}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid var(--border)",
            borderRadius: 4,
            padding: "3px 8px",
            color: "var(--text-muted)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
          }}
        >
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
        {tcus.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 8 }}>
            No tasks yet. Use <code>ashi task "..."</code> to create one.
          </div>
        )}
        {tcus.map((tcu) => (
          <div
            key={tcu.id}
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "10px 12px",
              marginBottom: 8,
              borderLeft: `3px solid ${STATUS_COLOR[tcu.status] ?? "var(--border)"}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ color: "var(--text)", fontSize: 12, fontWeight: 500 }}>
                {tcu.intent}
              </span>
              <span style={{
                color: STATUS_COLOR[tcu.status],
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: 1,
              }}>
                {tcu.status}
              </span>
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
              {tcu.id} · {new Date(tcu.created_at).toLocaleString()}
            </div>
            {tcu.judge && (
              <div style={{
                marginTop: 6,
                padding: "4px 8px",
                background: "var(--surface2)",
                borderRadius: 4,
                fontSize: 11,
                display: "flex",
                gap: 12,
              }}>
                <span style={{ color: STATUS_COLOR[tcu.judge.verdict === "pass" ? "done" : "failed"] }}>
                  {tcu.judge.verdict}
                </span>
                <span style={{ color: "var(--text-muted)" }}>{tcu.judge.score}/10</span>
                <span style={{ color: "var(--text-muted)" }}>{tcu.judge.notes}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
