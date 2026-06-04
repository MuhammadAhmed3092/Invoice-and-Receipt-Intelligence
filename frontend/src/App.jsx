import { useState, useRef, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

const STATUS_META = {
  approved:   { color: "#1D9E75", bg: "#E1F5EE", label: "Approved"     },
  review:     { color: "#BA7517", bg: "#FAEEDA", label: "Needs Review"  },
  error:      { color: "#D85A30", bg: "#FAECE7", label: "Error"         },
  processing: { color: "#378ADD", bg: "#E6F1FB", label: "Processing…"   },
  pending:    { color: "#888780", bg: "#F1EFE8", label: "Pending"       },
};

const FLAG_LABELS = {
  math_error:         "Math error",
  tax_mismatch:       "Tax mismatch",
  missing_vendor:     "No vendor",
  missing_total:      "No total",
  missing_date:       "No date",
  missing_number:     "No inv. number",
  duplicate_possible: "Possible duplicate",
  low_confidence:     "Low confidence",
};

function ConfidenceBar({ value }) {
  const pct   = Math.round(value * 100);
  const color = pct >= 90 ? "#1D9E75" : pct >= 75 ? "#BA7517" : "#D85A30";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 4, background: "#eee", borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: 4, background: color,
                      borderRadius: 2, transition: "width 0.4s" }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 500, color, minWidth: 34 }}>{pct}%</span>
    </div>
  );
}

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.pending;
  return (
    <span style={{ fontSize: 11, padding: "2px 9px", borderRadius: 99,
                   background: m.bg, color: m.color, fontWeight: 500 }}>
      {m.label}
    </span>
  );
}

function FlagBadge({ flag }) {
  return (
    <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 99,
                   background: "#FAECE7", color: "#993C1D", fontWeight: 500 }}>
      {FLAG_LABELS[flag] || flag}
    </span>
  );
}

function InvoiceCard({ inv, index }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ background: "#fff", border: "1px solid #e8e8e8",
                  borderRadius: 10, overflow: "hidden",
                  borderLeft: `3px solid ${STATUS_META[inv.status]?.color || "#ddd"}` }}>
      <div onClick={() => setOpen(o => !o)}
           style={{ padding: "12px 16px", cursor: "pointer",
                    display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 13, color: "#999", minWidth: 20 }}>#{index + 1}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 500, fontSize: 14, color: "#1a1a1a",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {inv.vendor_name || inv.filename}
          </div>
          <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>
            {inv.invoice_number && <span>{inv.invoice_number} · </span>}
            {inv.invoice_date && <span>{inv.invoice_date} · </span>}
            {inv.grand_total > 0 && (
              <span style={{ fontWeight: 500, color: "#333" }}>
                {inv.currency} {inv.grand_total.toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          <StatusBadge status={inv.status} />
          <div style={{ width: 120 }}>
            <ConfidenceBar value={inv.confidence || 0} />
          </div>
        </div>
        <span style={{ color: "#ccc", fontSize: 12 }}>{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div style={{ padding: "0 16px 16px", borderTop: "1px solid #f0f0f0" }}>
          {inv.flags?.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {inv.flags.map(f => <FlagBadge key={f} flag={f} />)}
            </div>
          )}
          <div style={{ marginTop: 10, display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: "6px 16px", fontSize: 13 }}>
            {[
              ["Vendor",         inv.vendor_name],
              ["Invoice #",      inv.invoice_number],
              ["Date",           inv.invoice_date],
              ["Currency",       inv.currency],
              ["Grand Total",    inv.grand_total > 0
                                   ? `${inv.currency} ${Number(inv.grand_total).toLocaleString("en-US", { minimumFractionDigits: 2 })}`
                                   : "—"],
              ["Line Items",     inv.line_item_count],
              ["Confidence",     inv.confidence ? `${Math.round(inv.confidence * 100)}%` : "—"],
              ["File",           inv.filename],
            ].map(([k, v]) => v ? (
              <div key={k} style={{ display: "flex", gap: 6 }}>
                <span style={{ color: "#999", minWidth: 80 }}>{k}</span>
                <span style={{ color: "#333", fontWeight: 500 }}>{v}</span>
              </div>
            ) : null)}
          </div>
          {inv.error && (
            <div style={{ marginTop: 10, padding: "8px 12px", background: "#fff0f0",
                          borderRadius: 6, fontSize: 12, color: "#c00" }}>
              ⚠ {inv.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [files,       setFiles]       = useState([]);
  const [uploading,   setUploading]   = useState(false);
  const [processing,  setProcessing]  = useState(false);
  const [results,     setResults]     = useState([]);
  const [progress,    setProgress]    = useState({ current: 0, total: 0, message: "" });
  const [summary,     setSummary]     = useState(null);
  const [exportFmt,   setExportFmt]   = useState("excel");
  const [exportPath,  setExportPath]  = useState("");
  const [error,       setError]       = useState("");
  const [dragOver,    setDragOver]    = useState(false);
  const fileRef  = useRef();
  const savedRef = useRef([]);   // saved_as filenames from /upload

  const addFiles = useCallback((newFiles) => {
    const valid = Array.from(newFiles).filter(f =>
      /\.(pdf|png|jpg|jpeg|tiff|bmp|webp)$/i.test(f.name)
    );
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name));
      return [...prev, ...valid.filter(f => !names.has(f.name))];
    });
  }, []);

  const onDrop = useCallback((e) => {
    e.preventDefault(); setDragOver(false);
    addFiles(e.dataTransfer.files);
  }, [addFiles]);

  const removeFile = (name) => setFiles(prev => prev.filter(f => f.name !== name));

  async function uploadAndProcess() {
    if (!files.length) return;
    setError(""); setResults([]); setSummary(null); setExportPath("");
    setUploading(true);
    setProgress({ current: 0, total: files.length, message: "Uploading files…" });

    try {
      // Upload
      const form = new FormData();
      files.forEach(f => form.append("files", f));
      const upRes  = await fetch(`${API}/upload`, { method: "POST", body: form });
      if (!upRes.ok) throw new Error(`Upload failed: ${upRes.status}`);
      const upData = await upRes.json();
      savedRef.current = upData.uploaded.map(u => u.saved_as);
      setUploading(false);

      // Process with SSE stream
      setProcessing(true);
      setProgress({ current: 0, total: files.length, message: "Starting extraction…" });

      const procRes = await fetch(`${API}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filenames: savedRef.current, export_fmt: exportFmt }),
      });

      const reader  = procRes.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();

        for (const part of parts) {
          const eLine = part.split("\n").find(l => l.startsWith("event:"));
          const dLine = part.split("\n").find(l => l.startsWith("data:"));
          if (!eLine || !dLine) continue;
          const event = eLine.replace("event:", "").trim();
          const data  = JSON.parse(dLine.replace("data:", "").trim());

          if (event === "start") {
            setProgress({ current: 0, total: data.total, message: data.message });
          }
          if (event === "progress") {
            setProgress({ current: data.current, total: data.total, message: data.message });
          }
          if (event === "result") {
            setResults(prev => [...prev, data]);
            setProgress(p => ({ ...p, current: data.current, message: `Processed: ${data.filename}` }));
          }
          if (event === "complete") {
            setSummary(data);
            setExportPath(data.export_path);
            setProcessing(false);
          }
          if (event === "error") {
            setError(data.message);
            setProcessing(false);
          }
        }
      }
    } catch (e) {
      setError(e.message);
      setUploading(false);
      setProcessing(false);
    }
  }

  async function downloadExport() {
    const res  = await fetch(`${API}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fmt: exportFmt }),
    });
    if (!res.ok) { setError("Export failed"); return; }
    const blob = await res.blob();
    const ext  = exportFmt === "excel" ? "xlsx" : exportFmt === "csv" ? "csv" : "json";
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = `invoices.${ext}`; a.click();
    URL.revokeObjectURL(url);
  }

  const busy = uploading || processing;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1rem",
                  fontFamily: "'Inter', system-ui, sans-serif" }}>

      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, color: "#1a1a1a" }}>
          🧾 Invoice Intelligence
        </h1>
        <p style={{ color: "#777", marginTop: 5, fontSize: 13 }}>
          AI extraction · math verification · confidence scoring · Excel export
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !busy && fileRef.current.click()}
        style={{
          border: `2px dashed ${dragOver ? "#534AB7" : "#ddd"}`,
          borderRadius: 12, padding: "32px 20px", textAlign: "center",
          background: dragOver ? "#F5F4FE" : "#fafafa",
          cursor: busy ? "not-allowed" : "pointer",
          transition: "all 0.15s", marginBottom: 16,
        }}>
        <input ref={fileRef} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
               style={{ display: "none" }}
               onChange={e => addFiles(e.target.files)} />
        <div style={{ fontSize: 32, marginBottom: 8 }}>📂</div>
        <div style={{ fontWeight: 500, color: "#333", fontSize: 15 }}>
          Drop invoices here or click to browse
        </div>
        <div style={{ color: "#999", fontSize: 13, marginTop: 4 }}>
          PDF, PNG, JPG, TIFF — single or batch
        </div>
      </div>

      {/* File queue */}
      {files.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "#555",
                        marginBottom: 8 }}>
            {files.length} file{files.length > 1 ? "s" : ""} queued
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {files.map(f => (
              <div key={f.name} style={{ display: "flex", alignItems: "center", gap: 6,
                                         padding: "4px 10px", background: "#f0f0f0",
                                         borderRadius: 99, fontSize: 13 }}>
                <span style={{ maxWidth: 180, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {f.name}
                </span>
                {!busy && (
                  <button onClick={e => { e.stopPropagation(); removeFile(f.name); }}
                          style={{ background: "none", border: "none", cursor: "pointer",
                                   color: "#999", fontSize: 14, padding: 0, lineHeight: 1 }}>
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Controls row */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, alignItems: "center" }}>
        <button
          onClick={uploadAndProcess}
          disabled={busy || !files.length}
          style={{ padding: "10px 24px", fontSize: 14, fontWeight: 600,
                   background: busy || !files.length ? "#bbb" : "#534AB7",
                   color: "#fff", border: "none", borderRadius: 8,
                   cursor: busy || !files.length ? "not-allowed" : "pointer" }}>
          {uploading ? "Uploading…" : processing ? "Extracting…" : "Extract Invoices ↗"}
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: 6,
                      fontSize: 13, color: "#555" }}>
          <span>Export as</span>
          <select value={exportFmt} onChange={e => setExportFmt(e.target.value)}
                  disabled={busy}
                  style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid #ddd",
                           fontSize: 13, background: "#fff" }}>
            <option value="excel">Excel (.xlsx)</option>
            <option value="csv">CSV (.csv)</option>
            <option value="json">JSON (.json)</option>
          </select>
        </div>

        {summary && (
          <button onClick={downloadExport}
                  style={{ padding: "10px 18px", fontSize: 13, fontWeight: 500,
                           background: "#1D9E75", color: "#fff",
                           border: "none", borderRadius: 8, cursor: "pointer",
                           marginLeft: "auto" }}>
            ⬇ Download {exportFmt.toUpperCase()}
          </button>
        )}
      </div>

      {/* Progress bar */}
      {busy && (
        <div style={{ marginBottom: 20, padding: "14px 16px",
                      background: "#f0f0f0", borderRadius: 10 }}>
          <div style={{ fontSize: 13, color: "#444", marginBottom: 8 }}>
            {progress.message}
          </div>
          <div style={{ height: 6, background: "#ddd", borderRadius: 3 }}>
            <div style={{
              height: 6, borderRadius: 3, background: "#534AB7",
              width: progress.total > 0
                ? `${(progress.current / progress.total) * 100}%` : "10%",
              transition: "width 0.4s",
            }} />
          </div>
          {progress.total > 0 && (
            <div style={{ fontSize: 12, color: "#888", marginTop: 6 }}>
              {progress.current} / {progress.total}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ padding: "12px 16px", background: "#fff0f0",
                      border: "1px solid #fcc", borderRadius: 8,
                      color: "#c00", fontSize: 14, marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      {/* Summary bar */}
      {summary && (
        <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
          {[
            { label: "Total",        val: summary.total,        color: "#534AB7" },
            { label: "Approved",     val: summary.approved,     color: "#1D9E75" },
            { label: "Needs Review", val: summary.needs_review, color: "#BA7517" },
            { label: "Errors",       val: summary.errors,       color: "#D85A30" },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ flex: 1, minWidth: 100, padding: "12px 16px",
                                      background: "#fff", border: "1px solid #eee",
                                      borderRadius: 10, textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700, color }}>{val}</div>
              <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Results list */}
      {results.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: "#555", marginBottom: 12 }}>
            Results — click any row to expand
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {results.map((inv, i) => (
              <InvoiceCard key={inv.invoice_id || i} inv={inv} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* Footer debug */}
      <div style={{ marginTop: 40, fontSize: 11, color: "#ccc" }}>
        API: {API}
      </div>
    </div>
  );
}