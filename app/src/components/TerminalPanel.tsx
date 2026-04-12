import { useState, useRef, useEffect } from "react";
import { Terminal, ChevronRight } from "lucide-react";
import { runShell } from "../api";

interface ShellLine {
  type: "cmd" | "stdout" | "stderr" | "meta";
  text: string;
}

const DEFAULT_CWD = "~/Desktop/SecondBrain";

export default function TerminalPanel() {
  const [lines, setLines] = useState<ShellLine[]>([
    { type: "meta", text: "ASHI Terminal — bash -c, max 120s. Type a command and press Enter." },
    { type: "meta", text: `cwd: ${DEFAULT_CWD}` },
  ]);
  const [input, setInput] = useState("");
  const [cwd, setCwd] = useState(DEFAULT_CWD);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  async function run() {
    const cmd = input.trim();
    if (!cmd || running) return;
    setInput("");
    setHistIdx(-1);
    setHistory((prev) => [cmd, ...prev].slice(0, 100));

    setLines((prev) => [...prev, { type: "cmd", text: `${cwd} $ ${cmd}` }]);
    setRunning(true);

    // Handle built-in cd
    if (cmd.startsWith("cd ")) {
      const target = cmd.slice(3).trim();
      const newCwd = target.startsWith("/") || target.startsWith("~")
        ? target
        : `${cwd}/${target}`;
      setCwd(newCwd);
      setLines((prev) => [...prev, { type: "meta", text: `cwd: ${newCwd}` }]);
      setRunning(false);
      return;
    }

    if (cmd === "clear") {
      setLines([{ type: "meta", text: `cwd: ${cwd}` }]);
      setRunning(false);
      return;
    }

    try {
      const result = await runShell(cmd, cwd, 60);
      if (result.stdout) {
        for (const line of result.stdout.split("\n")) {
          setLines((prev) => [...prev, { type: "stdout", text: line }]);
        }
      }
      if (result.stderr) {
        for (const line of result.stderr.split("\n")) {
          if (line.trim()) setLines((prev) => [...prev, { type: "stderr", text: line }]);
        }
      }
      if (result.timed_out) {
        setLines((prev) => [...prev, { type: "meta", text: `[timed out after 60s]` }]);
      } else {
        setLines((prev) => [...prev, { type: "meta", text: `exit ${result.exit_code}` }]);
      }
    } catch (err) {
      setLines((prev) => [...prev, { type: "stderr", text: String(err) }]);
    } finally {
      setRunning(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      run();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(histIdx + 1, history.length - 1);
      setHistIdx(next);
      if (history[next] !== undefined) setInput(history[next]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.max(histIdx - 1, -1);
      setHistIdx(next);
      setInput(next === -1 ? "" : history[next]);
    }
  }

  function lineColor(type: ShellLine["type"]) {
    switch (type) {
      case "cmd":    return "var(--accent)";
      case "stdout": return "var(--text)";
      case "stderr": return "#f87171";
      case "meta":   return "var(--text-muted)";
    }
  }

  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      background: "#0d0d0d",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 12,
      overflow: "hidden",
    }}
      onClick={() => inputRef.current?.focus()}
    >
      {/* Header */}
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        background: "var(--surface)",
      }}>
        <Terminal size={13} color="var(--green)" />
        <span style={{ color: "var(--green)", fontWeight: 600, fontSize: 11 }}>TERMINAL</span>
        <span style={{ color: "var(--text-muted)", fontSize: 10 }}>{cwd}</span>
      </div>

      {/* Output */}
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 12px", lineHeight: 1.6 }}>
        {lines.map((line, i) => (
          <div key={i} style={{ color: lineColor(line.type), whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {line.text}
          </div>
        ))}
        {running && (
          <div style={{ color: "var(--text-muted)", animation: "pulse 1s infinite" }}>▌</div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input row */}
      <div style={{
        borderTop: "1px solid var(--border)",
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 6,
        background: "var(--surface)",
      }}>
        <ChevronRight size={12} color="var(--accent)" />
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={running}
          placeholder={running ? "running..." : "command"}
          autoFocus
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: "var(--text)",
            fontSize: 12,
            fontFamily: "inherit",
          }}
        />
      </div>
    </div>
  );
}
