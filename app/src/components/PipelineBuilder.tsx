import { useCallback, useState } from "react";
import type { Skill } from "../types";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  BackgroundVariant,
} from "reactflow";
import "reactflow/dist/style.css";
import { runSkill, dispatchTool } from "../api";

const NODE_COLORS: Record<string, string> = {
  input:     "#4ade80",
  agent:     "#7c6af7",
  function:  "#60a5fa",
  condition: "#fbbf24",
  output:    "#f87171",
};

const STATUS_COLORS: Record<string, string> = {
  idle:    "transparent",
  running: "#fbbf24",
  done:    "#4ade80",
  error:   "#f87171",
};

interface NodeData {
  label: string;
  type: string;
  skill?: string;
  tool?: string;
  status?: "idle" | "running" | "done" | "error";
  output?: string;
}

function AshiNode({ data }: { data: NodeData }) {
  const color = NODE_COLORS[data.type] ?? "#666";
  const statusColor = STATUS_COLORS[data.status ?? "idle"];
  return (
    <div style={{
      background: "var(--surface2)",
      border: `1px solid ${color}`,
      borderRadius: 6,
      padding: "8px 12px",
      minWidth: 140,
      fontSize: 11,
      outline: data.status === "running" ? `2px solid ${statusColor}` : "none",
      outlineOffset: 2,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
        <div style={{ color, fontWeight: 600, textTransform: "uppercase", fontSize: 9, letterSpacing: 1 }}>
          {data.type}
        </div>
        {data.status && data.status !== "idle" && (
          <div style={{
            width: 7, height: 7, borderRadius: "50%",
            background: statusColor, flexShrink: 0,
          }} />
        )}
      </div>
      <div style={{ color: "var(--text)" }}>{data.label}</div>
      {data.skill && (
        <div style={{ color: "var(--text-muted)", fontSize: 10, marginTop: 2 }}>/{data.skill}</div>
      )}
      {data.tool && (
        <div style={{ color: "var(--text-muted)", fontSize: 10, marginTop: 2 }}>fn:{data.tool}</div>
      )}
      {data.output && (
        <div style={{
          marginTop: 6,
          padding: "4px 6px",
          background: "rgba(0,0,0,0.3)",
          borderRadius: 3,
          color: "var(--text-muted)",
          fontSize: 10,
          maxWidth: 180,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {data.output}
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { ashi: AshiNode };

const INITIAL_NODES: Node[] = [
  { id: "1", type: "ashi", position: { x: 100, y: 150 }, data: { label: "User Intent", type: "input" } },
  { id: "2", type: "ashi", position: { x: 320, y: 80  }, data: { label: "Router",     type: "agent",    skill: "plan"     } },
  { id: "3", type: "ashi", position: { x: 320, y: 220 }, data: { label: "Researcher", type: "agent",    skill: "research" } },
  { id: "4", type: "ashi", position: { x: 540, y: 150 }, data: { label: "Wiki Update",type: "function", tool: "update_entity" } },
  { id: "5", type: "ashi", position: { x: 760, y: 150 }, data: { label: "Judge",      type: "agent",    skill: "review"   } },
  { id: "6", type: "ashi", position: { x: 980, y: 150 }, data: { label: "Output",     type: "output"   } },
];

const INITIAL_EDGES: Edge[] = [
  { id: "e1-2", source: "1", target: "2", animated: true },
  { id: "e1-3", source: "1", target: "3", animated: true },
  { id: "e2-4", source: "2", target: "4" },
  { id: "e3-4", source: "3", target: "4" },
  { id: "e4-5", source: "4", target: "5", animated: true },
  { id: "e5-6", source: "5", target: "6" },
];

const NODE_PALETTE = [
  { type: "input",     label: "Input"     },
  { type: "agent",     label: "Agent"     },
  { type: "function",  label: "Function"  },
  { type: "condition", label: "Condition" },
  { type: "output",    label: "Output"    },
];

/** Topological sort — returns node IDs in execution order. */
function topoSort(nodes: Node[], edges: Edge[]): string[] {
  const inDegree: Record<string, number> = {};
  const adj: Record<string, string[]> = {};
  for (const n of nodes) { inDegree[n.id] = 0; adj[n.id] = []; }
  for (const e of edges) {
    adj[e.source].push(e.target);
    inDegree[e.target] = (inDegree[e.target] ?? 0) + 1;
  }
  const queue = nodes.filter(n => inDegree[n.id] === 0).map(n => n.id);
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    for (const next of adj[id]) {
      inDegree[next]--;
      if (inDegree[next] === 0) queue.push(next);
    }
  }
  return order;
}

export default function PipelineBuilder({ skills }: { skills: Skill[] }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState(INITIAL_EDGES);
  const [selectedSkill, setSelectedSkill] = useState("research");
  const [running, setRunning] = useState(false);
  const [intent, setIntent] = useState("research ASHI architecture");
  const [log, setLog] = useState<string[]>([]);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge({ ...connection, animated: true }, eds)),
    [setEdges]
  );

  function addNode(type: string) {
    const id = `node_${Date.now()}`;
    const newNode: Node = {
      id,
      type: "ashi",
      position: { x: 200 + Math.random() * 300, y: 100 + Math.random() * 200 },
      data: {
        label: type === "agent" ? `Agent (${selectedSkill})` : type.charAt(0).toUpperCase() + type.slice(1),
        type,
        skill: type === "agent" ? selectedSkill : undefined,
        status: "idle",
      },
    };
    setNodes((nds) => [...nds, newNode]);
  }

  function setNodeStatus(id: string, status: NodeData["status"], output?: string) {
    setNodes(nds => nds.map(n =>
      n.id === id ? { ...n, data: { ...n.data, status, ...(output ? { output } : {}) } } : n
    ));
  }

  async function runPipeline() {
    if (running) return;
    setRunning(true);
    setLog([]);

    // reset all node statuses
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: "idle", output: undefined } })));

    const order = topoSort(nodes, edges);
    const outputs: Record<string, string> = {};
    const baseContext = {
      topic: intent, goal: intent, spec: intent, depth: "brief",
      context: "", existing_code: "", language: "python",
      artifact: intent, criteria: "correctness", source: intent,
      label: "pipeline", date: new Date().toISOString().slice(0, 10),
      projects: "ashi", intent_entries: intent, tcu_count: "1",
      entity_name: intent.slice(0, 40), entity_type: "concept",
      new_facts: "", focus: "key facts", task: intent, current_state: "",
    };

    const addLog = (msg: string) => setLog(l => [...l, msg]);

    for (const nodeId of order) {
      const node = nodes.find(n => n.id === nodeId);
      if (!node) continue;
      const data = node.data as NodeData;

      if (data.type === "input" || data.type === "output" || data.type === "condition") {
        setNodeStatus(nodeId, "done", data.type === "input" ? intent : "done");
        continue;
      }

      setNodeStatus(nodeId, "running");
      addLog(`→ [${data.label}] starting...`);

      try {
        if (data.type === "agent" && data.skill) {
          // merge previous outputs into context
          const ctx = { ...baseContext, context: Object.values(outputs).join("\n\n").slice(0, 500) };
          const result = await runSkill(data.skill, ctx);
          const out = result.output.slice(0, 120);
          outputs[nodeId] = result.output;
          setNodeStatus(nodeId, "done", out);
          addLog(`✓ [${data.label}] ${result.tokens_used} tokens via ${result.model}`);

        } else if (data.type === "function" && data.tool) {
          const prevOutput = Object.values(outputs).at(-1) ?? intent;
          const result = await dispatchTool(data.tool, {
            name: intent.slice(0, 40),
            entity_type: "concept",
            facts: [prevOutput.slice(0, 200)],
          });
          const out = JSON.stringify(result).slice(0, 100);
          outputs[nodeId] = out;
          setNodeStatus(nodeId, "done", out);
          addLog(`✓ [${data.label}] tool ok`);
        }
      } catch (err) {
        setNodeStatus(nodeId, "error", String(err).slice(0, 80));
        addLog(`✗ [${data.label}] ${String(err).slice(0, 60)}`);
      }
    }

    setRunning(false);
    addLog("Pipeline complete.");
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative" }}>
      {/* Toolbar */}
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        gap: 8,
        alignItems: "center",
        background: "var(--surface)",
        flexShrink: 0,
        flexWrap: "wrap",
      }}>
        <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11 }}>PIPELINE</span>
        {NODE_PALETTE.map((n) => (
          <button
            key={n.type}
            onClick={() => addNode(n.type)}
            style={{
              background: "var(--surface2)",
              border: `1px solid ${NODE_COLORS[n.type]}`,
              borderRadius: 4,
              padding: "3px 8px",
              color: NODE_COLORS[n.type],
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            + {n.label}
          </button>
        ))}
        <select
          value={selectedSkill}
          onChange={(e) => setSelectedSkill(e.target.value)}
          style={{
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
            padding: "3px 6px",
            fontSize: 11,
          }}
        >
          {skills.filter(s => s.system === "ollama").map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </select>
        <input
          value={intent}
          onChange={e => setIntent(e.target.value)}
          placeholder="Intent / input text..."
          style={{
            flex: 1,
            minWidth: 160,
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
            padding: "3px 8px",
            fontSize: 11,
            fontFamily: "inherit",
            outline: "none",
          }}
        />
        <button
          onClick={running ? undefined : runPipeline}
          style={{
            background: running ? "var(--red)" : "var(--accent)",
            border: "none",
            borderRadius: 4,
            padding: "4px 14px",
            color: "#fff",
            fontSize: 11,
            cursor: running ? "not-allowed" : "pointer",
            opacity: running ? 0.7 : 1,
            flexShrink: 0,
          }}
        >
          {running ? "■ Running..." : "▶ Run"}
        </button>
      </div>

      {/* Canvas + log */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <div style={{ flex: 1 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            fitView
            style={{ background: "var(--bg)" }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#222" />
            <Controls />
            <MiniMap
              nodeColor={(n) => NODE_COLORS[(n.data as NodeData).type] ?? "#444"}
              maskColor="rgba(0,0,0,0.6)"
            />
          </ReactFlow>
        </div>

        {/* Execution log */}
        {log.length > 0 && (
          <div style={{
            width: 240,
            borderLeft: "1px solid var(--border)",
            background: "var(--surface)",
            overflowY: "auto",
            padding: "8px 10px",
            fontSize: 11,
            flexShrink: 0,
          }}>
            <div style={{ color: "var(--accent)", fontWeight: 600, marginBottom: 8, fontSize: 10 }}>
              EXECUTION LOG
            </div>
            {log.map((line, i) => (
              <div key={i} style={{
                color: line.startsWith("✗") ? "var(--red)" : line.startsWith("✓") ? "var(--green)" : "var(--text-muted)",
                marginBottom: 4,
                lineHeight: 1.5,
                wordBreak: "break-word",
              }}>
                {line}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
