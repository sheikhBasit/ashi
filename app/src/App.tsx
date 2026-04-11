import { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import PipelineBuilder from "./components/PipelineBuilder";
import WikiViewer from "./components/WikiViewer";
import TasksView from "./components/TasksView";
import TerminalPanel from "./components/TerminalPanel";
import MonitorPanel from "./components/MonitorPanel";
import AgentPanel from "./components/AgentPanel";
import type { Panel, TCU, Skill } from "./types";
import { listSkills, listTCUs } from "./api";

export default function App() {
  const [panel, setPanel] = useState<Panel>("pipeline");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tcus, setTcus] = useState<TCU[]>([]);

  useEffect(() => {
    listSkills().then(setSkills).catch(console.error);
    listTCUs().then(setTcus).catch(console.error);
  }, []);

  const activeTcus = tcus.filter(
    (t) => t.status === "running" || t.status === "pending",
  );

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar
        active={panel}
        onSelect={setPanel}
        skills={skills}
        tculCount={activeTcus.length}
      />

      <main style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {panel === "pipeline" && <PipelineBuilder skills={skills} />}
        {panel === "wiki" && <WikiViewer />}
        {panel === "tasks" && (
          <TasksView tcus={tcus} onRefresh={() => listTCUs().then(setTcus)} />
        )}
        {panel === "terminal" && <TerminalPanel />}
        {panel === "monitor" && <MonitorPanel />}
        {panel === "logs" && <LogsView />}
        {panel === "agent" && <AgentPanel />}
      </main>

      <ChatPanel skills={skills} />
    </div>
  );
}

function LogsView() {
  return (
    <div style={{ flex: 1, padding: 16, overflowY: "auto" }}>
      <div
        style={{
          color: "var(--accent)",
          fontWeight: 600,
          fontSize: 11,
          marginBottom: 12,
        }}
      >
        LOGS
      </div>
      <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
        Logs are written to:
        <br />
        <code style={{ color: "var(--text)" }}>
          ~/Desktop/SecondBrain/AI/agent-logs/
        </code>
        <br />
        <br />
        Ralph Loop runs at 03:00 daily.
        <br />
        Langfuse traces at{" "}
        <code style={{ color: "var(--text)" }}>localhost:3100</code>
      </div>
    </div>
  );
}
