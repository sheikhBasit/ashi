import { useState, useEffect, useCallback } from "react";
import { Activity } from "lucide-react";
import { getMonitorStats } from "../api";
import type { MonitorData, ServiceStatus } from "../types";

// ---- Sub-components ----

function ProgressBar({ percent, color = "var(--accent)" }: { percent: number; color?: string }) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <div style={{
      height: 4,
      background: "var(--border)",
      borderRadius: 2,
      marginTop: 4,
      overflow: "hidden",
    }}>
      <div style={{
        height: "100%",
        width: `${clamped}%`,
        background: color,
        borderRadius: 2,
        transition: "width 0.4s ease",
      }} />
    </div>
  );
}

function StatCard({ label, value, sub, percent, barColor }: {
  label: string;
  value: string;
  sub?: string;
  percent?: number;
  barColor?: string;
}) {
  return (
    <div style={{
      background: "var(--surface2)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      padding: "10px 12px",
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ color: "var(--text-muted)", fontSize: 9, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ color: "var(--text)", fontSize: 18, fontWeight: 700, fontFamily: "monospace", lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ color: "var(--text-muted)", fontSize: 10, marginTop: 3 }}>{sub}</div>
      )}
      {percent !== undefined && (
        <ProgressBar percent={percent} color={barColor ?? (percent > 80 ? "#f87171" : percent > 60 ? "#fbbf24" : "var(--accent)")} />
      )}
    </div>
  );
}

function ServiceDot({ name, info }: { name: string; info: ServiceStatus }) {
  const up = info.status === "up";
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 8,
      padding: "6px 10px",
      background: "var(--surface2)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      flex: 1,
      minWidth: 0,
    }}>
      <span style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: up ? "var(--green)" : "#f87171",
        flexShrink: 0,
        boxShadow: up ? "0 0 4px var(--green)" : "none",
      }} />
      <span style={{ color: "var(--text)", fontSize: 11, fontFamily: "monospace", flex: 1 }}>{name}</span>
      {info.latency_ms !== null ? (
        <span style={{ color: "var(--text-muted)", fontSize: 10, fontFamily: "monospace" }}>
          {info.latency_ms}ms
        </span>
      ) : (
        <span style={{ color: "#f87171", fontSize: 10 }}>down</span>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: "var(--accent)",
      fontSize: 9,
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: 1.5,
      marginBottom: 6,
      marginTop: 14,
    }}>
      {children}
    </div>
  );
}

// ---- Main Panel ----

export default function MonitorPanel() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [tick, setTick] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getMonitorStats();
      setData(result);
      setLastUpdated(new Date().toLocaleTimeString());
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-refresh every 3 seconds
  useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1);
    }, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (tick > 0) refresh();
  }, [tick, refresh]);

  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      background: "#0d0d0d",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 12,
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        background: "var(--surface)",
        flexShrink: 0,
      }}>
        <Activity size={13} color="var(--accent)" />
        <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11 }}>MONITOR</span>
        <span style={{ color: "var(--text-muted)", fontSize: 10, flex: 1 }}>
          {lastUpdated ? `updated ${lastUpdated}` : "loading..."}
        </span>
        {loading && (
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>&#9632; refreshing</span>
        )}
        <button
          onClick={refresh}
          disabled={loading}
          style={{
            background: "transparent",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
            fontSize: 10,
            padding: "2px 8px",
            borderRadius: 3,
            cursor: loading ? "default" : "pointer",
          }}
        >
          refresh
        </button>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
        {error && (
          <div style={{ color: "#f87171", fontSize: 11, marginBottom: 10 }}>
            Error: {error}
          </div>
        )}

        {data && (
          <>
            {/* ---- System row ---- */}
            <SectionLabel>System</SectionLabel>
            <div style={{ display: "flex", gap: 8 }}>
              <StatCard
                label="CPU"
                value={`${data.system.cpu_percent.toFixed(1)}%`}
                percent={data.system.cpu_percent}
              />
              <StatCard
                label="RAM"
                value={`${data.system.ram_used_gb}GB`}
                sub={`of ${data.system.ram_total_gb}GB`}
                percent={data.system.ram_percent}
              />
              <StatCard
                label="Disk"
                value={`${data.system.disk_used_gb}GB`}
                sub={`of ${data.system.disk_total_gb}GB`}
                percent={data.system.disk_percent}
              />
              <StatCard
                label="Swap"
                value={`${data.system.swap_used_gb}GB`}
                sub={`of ${data.system.swap_total_gb}GB`}
                percent={data.system.swap_total_gb > 0
                  ? (data.system.swap_used_gb / data.system.swap_total_gb) * 100
                  : 0}
              />
            </div>

            {/* ---- Services row ---- */}
            <SectionLabel>Services</SectionLabel>
            <div style={{ display: "flex", gap: 8 }}>
              {Object.entries(data.services).map(([name, info]) => (
                <ServiceDot key={name} name={name} info={info} />
              ))}
            </div>

            {/* ---- Network row ---- */}
            <SectionLabel>Network (since boot)</SectionLabel>
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{
                background: "var(--surface2)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: "8px 12px",
                flex: 1,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}>
                <span style={{ color: "var(--text-muted)", fontSize: 10 }}>TX</span>
                <span style={{ color: "var(--text)", fontFamily: "monospace", fontSize: 13, fontWeight: 700 }}>
                  {data.network.bytes_sent_mb.toFixed(1)} MB
                </span>
              </div>
              <div style={{
                background: "var(--surface2)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: "8px 12px",
                flex: 1,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}>
                <span style={{ color: "var(--text-muted)", fontSize: 10 }}>RX</span>
                <span style={{ color: "var(--green)", fontFamily: "monospace", fontSize: 13, fontWeight: 700 }}>
                  {data.network.bytes_recv_mb.toFixed(1)} MB
                </span>
              </div>
            </div>

            {/* ---- Processes table ---- */}
            <SectionLabel>Processes (top {data.processes.length} by CPU)</SectionLabel>
            <div style={{
              background: "var(--surface2)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              overflow: "hidden",
            }}>
              {/* Table header */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "60px 1fr 70px 80px 70px",
                padding: "5px 10px",
                borderBottom: "1px solid var(--border)",
                color: "var(--text-muted)",
                fontSize: 9,
                textTransform: "uppercase",
                letterSpacing: 1,
              }}>
                <span>PID</span>
                <span>Name</span>
                <span style={{ textAlign: "right" }}>CPU%</span>
                <span style={{ textAlign: "right" }}>Mem MB</span>
                <span style={{ textAlign: "right" }}>Status</span>
              </div>
              {/* Table rows */}
              {data.processes.map((proc) => {
                const highCpu = proc.cpu_percent > 50;
                return (
                  <div
                    key={proc.pid}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "60px 1fr 70px 80px 70px",
                      padding: "4px 10px",
                      borderBottom: "1px solid var(--border)",
                      fontSize: 11,
                      background: highCpu ? "rgba(248,113,113,0.07)" : "transparent",
                    }}
                  >
                    <span style={{ color: "var(--text-muted)", fontFamily: "monospace" }}>{proc.pid}</span>
                    <span style={{
                      color: highCpu ? "#f87171" : "var(--text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}>
                      {proc.name}
                    </span>
                    <span style={{
                      textAlign: "right",
                      color: highCpu ? "#f87171" : "var(--accent)",
                      fontFamily: "monospace",
                      fontWeight: highCpu ? 700 : 400,
                    }}>
                      {proc.cpu_percent.toFixed(1)}
                    </span>
                    <span style={{ textAlign: "right", color: "var(--text-muted)", fontFamily: "monospace" }}>
                      {proc.memory_mb.toFixed(1)}
                    </span>
                    <span style={{ textAlign: "right", color: "var(--text-muted)", fontSize: 10 }}>
                      {proc.status}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* ---- Cron jobs ---- */}
            {data.crons.length > 0 && (
              <>
                <SectionLabel>Cron Jobs</SectionLabel>
                <div style={{
                  background: "var(--surface2)",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  overflow: "hidden",
                }}>
                  {data.crons.map((cron, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 12,
                        padding: "5px 10px",
                        borderBottom: i < data.crons.length - 1 ? "1px solid var(--border)" : "none",
                        fontSize: 11,
                      }}
                    >
                      <span style={{
                        color: "var(--accent)",
                        fontFamily: "monospace",
                        whiteSpace: "nowrap",
                        flexShrink: 0,
                      }}>
                        {cron.schedule}
                      </span>
                      <span style={{
                        color: "var(--text-muted)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        flex: 1,
                      }}>
                        {cron.command}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {data.crons.length === 0 && (
              <>
                <SectionLabel>Cron Jobs</SectionLabel>
                <div style={{ color: "var(--text-muted)", fontSize: 11, padding: "4px 0" }}>
                  No crontab entries found.
                </div>
              </>
            )}

            {/* Bottom spacing */}
            <div style={{ height: 16 }} />
          </>
        )}

        {!data && !error && (
          <div style={{ color: "var(--text-muted)", fontSize: 11, padding: "20px 0" }}>
            Loading system stats...
          </div>
        )}
      </div>
    </div>
  );
}
