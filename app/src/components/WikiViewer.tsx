import { useState } from "react";
import { Search, FileText, RefreshCw } from "lucide-react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import type { WikiResult } from "../types";
import { searchWiki, readWikiFile } from "../api";

marked.setOptions({ breaks: true });

function renderMarkdown(raw: string): string {
  const html = marked.parse(raw) as string;
  return DOMPurify.sanitize(html);
}

export default function WikiViewer() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<WikiResult[]>([]);
  const [selected, setSelected] = useState<WikiResult | null>(null);
  const [fullContent, setFullContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);

  async function search() {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await searchWiki(query, 8);
      setResults(r);
      if (r.length > 0) await selectResult(r[0]);
    } finally {
      setLoading(false);
    }
  }

  async function selectResult(r: WikiResult) {
    setSelected(r);
    setFullContent("");
    setContentLoading(true);
    try {
      const content = await readWikiFile(r.path);
      setFullContent(content);
    } catch {
      setFullContent(r.snippet);
    } finally {
      setContentLoading(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") search();
  }

  const renderedHtml = fullContent ? renderMarkdown(fullContent) : "";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Search bar */}
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        display: "flex",
        gap: 8,
        alignItems: "center",
        flexShrink: 0,
      }}>
        <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11 }}>WIKI</span>
        <div style={{ flex: 1, display: "flex", gap: 6 }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search wiki (BM25)..."
            style={{
              flex: 1,
              background: "var(--surface2)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              color: "var(--text)",
              padding: "4px 8px",
              fontSize: 12,
              outline: "none",
              fontFamily: "inherit",
            }}
          />
          <button
            onClick={search}
            disabled={loading}
            style={{
              background: "var(--accent)",
              border: "none",
              borderRadius: 4,
              padding: "4px 10px",
              cursor: loading ? "not-allowed" : "pointer",
              color: "#fff",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? <RefreshCw size={13} /> : <Search size={13} />}
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Results list */}
        <div style={{
          width: 220,
          minWidth: 180,
          borderRight: "1px solid var(--border)",
          overflowY: "auto",
          background: "var(--surface)",
          flexShrink: 0,
        }}>
          {results.length === 0 ? (
            <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 12 }}>
              {loading ? "Searching..." : "Search to browse the wiki."}
            </div>
          ) : (
            results.map((r) => (
              <button
                key={r.path}
                onClick={() => selectResult(r)}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 6,
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  background: selected?.path === r.path ? "var(--accent-dim)" : "transparent",
                  border: "none",
                  borderBottom: "1px solid var(--border)",
                  borderLeft: selected?.path === r.path ? "2px solid var(--accent)" : "2px solid transparent",
                  cursor: "pointer",
                }}
              >
                <FileText size={12} style={{ color: "var(--accent)", marginTop: 2, flexShrink: 0 }} />
                <div>
                  <div style={{ color: "var(--text)", fontSize: 11, fontWeight: 500 }}>
                    {r.file.replace(/\.md$/, "").replace(/-/g, " ")}
                  </div>
                  <div style={{ color: "var(--text-muted)", fontSize: 10, marginTop: 2 }}>
                    score {r.score.toFixed(2)}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Rendered markdown */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
          {contentLoading ? (
            <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Loading...</div>
          ) : selected && renderedHtml ? (
            <>
              <div style={{ color: "var(--text-muted)", fontSize: 10, marginBottom: 12, fontFamily: "monospace" }}>
                {selected.path}
              </div>
              <div className="wiki-markdown" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
            </>
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
              Select a result to view its content.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
