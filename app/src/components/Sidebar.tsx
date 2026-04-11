import {
  Activity,
  BookOpen,
  Bot,
  GitBranch,
  LayoutGrid,
  ScrollText,
  Terminal,
  Zap,
} from "lucide-react";
import type { Panel, Skill } from "../types";

interface SidebarProps {
  active: Panel;
  onSelect: (p: Panel) => void;
  skills: Skill[];
  tculCount: number;
}

const NAV: { id: Panel; icon: React.ReactNode; label: string }[] = [
  { id: "pipeline", icon: <GitBranch size={16} />, label: "Pipeline" },
  { id: "wiki", icon: <BookOpen size={16} />, label: "Wiki" },
  { id: "tasks", icon: <LayoutGrid size={16} />, label: "Tasks" },
  { id: "terminal", icon: <Terminal size={16} />, label: "Terminal" },
  { id: "monitor", icon: <Activity size={16} />, label: "Monitor" },
  { id: "logs", icon: <ScrollText size={16} />, label: "Logs" },
  { id: "agent", icon: <Bot size={16} />, label: "Agent" },
];

export default function Sidebar({
  active,
  onSelect,
  skills,
  tculCount,
}: SidebarProps) {
  return (
    <aside
      style={{
        width: 200,
        minWidth: 200,
        background: "var(--surface)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        userSelect: "none",
      }}
    >
      {/* Logo */}
      <div
        style={{
          padding: "16px 12px 12px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Zap size={18} color="var(--accent)" />
          <span
            style={{
              fontWeight: 700,
              color: "var(--accent)",
              letterSpacing: 2,
            }}
          >
            ASHI
          </span>
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>v0.2</span>
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 10,
            marginTop: 2,
            paddingLeft: 26,
          }}
        >
          local AI OS
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: "8px 0" }}>
        {NAV.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              width: "100%",
              padding: "8px 12px",
              background:
                active === item.id ? "var(--accent-dim)" : "transparent",
              color: active === item.id ? "var(--accent)" : "var(--text-muted)",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              textAlign: "left",
              borderLeft:
                active === item.id
                  ? "2px solid var(--accent)"
                  : "2px solid transparent",
            }}
          >
            {item.icon}
            {item.label}
            {item.id === "tasks" && tculCount > 0 && (
              <span
                style={{
                  marginLeft: "auto",
                  background: "var(--accent)",
                  color: "#fff",
                  borderRadius: 8,
                  padding: "0 5px",
                  fontSize: 10,
                }}
              >
                {tculCount}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* Skills list */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "8px 0",
          flex: 1,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "4px 12px 6px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span
            style={{
              color: "var(--text-muted)",
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Skills
          </span>
          <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
            {skills.filter((s) => s.system === "ollama").length}L /{" "}
            {skills.filter((s) => s.system === "claude").length}C
          </span>
        </div>
        <div style={{ overflowY: "auto", maxHeight: 200 }}>
          {skills
            .filter((s) => s.system === "ollama" && !s.derived_from)
            .map((s) => (
              <div
                key={s.name}
                title={s.description}
                style={{
                  padding: "3px 12px 3px 20px",
                  color: "var(--green)",
                  fontSize: 11,
                  cursor: "default",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                /{s.name}
              </div>
            ))}
          {skills
            .filter((s) => s.system === "claude")
            .slice(0, 6)
            .map((s) => (
              <div
                key={s.name}
                title={`[${s.plugin}] ${s.description}`}
                style={{
                  padding: "3px 12px 3px 20px",
                  color: "var(--accent)",
                  fontSize: 11,
                  cursor: "default",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  opacity: 0.7,
                }}
              >
                ~{s.name}
              </div>
            ))}
          {skills.filter((s) => s.system === "claude").length > 6 && (
            <div
              style={{
                padding: "3px 12px 3px 20px",
                color: "var(--text-muted)",
                fontSize: 10,
              }}
            >
              +{skills.filter((s) => s.system === "claude").length - 6} more
              claude skills
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "8px 12px",
          fontSize: 10,
          color: "var(--text-muted)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>ollama</span>
          <span style={{ color: "var(--green)" }}>● live</span>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: 2,
          }}
        >
          <span>langfuse</span>
          <span style={{ color: "var(--green)" }}>● 3100</span>
        </div>
      </div>
    </aside>
  );
}
