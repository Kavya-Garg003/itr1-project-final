"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";

type DocType = "form16" | "bank_statement" | "auto";

interface ParsedDoc {
  doc_type:   DocType;
  filename:   string;
  confidence: number;
  data:       Record<string, unknown>;
  warnings:   string[];
  session_id: string;
}

// ── File card ──────────────────────────────────────────────────────────────

function FileCard({
  doc,
  onRemove,
}: {
  doc: ParsedDoc;
  onRemove: () => void;
}) {
  const conf    = Math.round(doc.confidence * 100);
  const confColor =
    conf >= 80 ? "text-green-400" : conf >= 50 ? "text-amber-400" : "text-red-400";

  return (
    <div className="glass-card rounded-xl p-4 relative group transition-all duration-300">
      <button
        onClick={onRemove}
        className="absolute top-2 right-2 text-slate-500 hover:text-white text-lg leading-none transition-colors"
      >
        ×
      </button>
      <div className="flex items-start gap-4">
        <div className="text-3xl p-3 bg-white/5 rounded-lg border border-white/10">
          {doc.doc_type === "form16" ? "📋" : "🏦"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-slate-100 truncate">{doc.filename}</div>
          <div className="text-xs text-slate-400 mt-1 uppercase tracking-wider font-medium">
            {doc.doc_type.replace("_", " ")}
          </div>
          <div className={`text-xs mt-1.5 font-medium ${confColor} flex items-center`}>
            <span className="w-2 h-2 rounded-full bg-current mr-2 animate-pulse bg-current" />
            {conf}% AI Confidence
          </div>
          {doc.warnings.length > 0 && (
            <div className="mt-3 space-y-1">
              {doc.warnings.map((w, i) => (
                <div key={i} className="text-xs text-amber-200 bg-amber-500/20 border border-amber-500/30 rounded px-2 py-1.5">
                  ⚠ {w}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Drop zone ──────────────────────────────────────────────────────────────

function DropZone({
  label,
  docType,
  onParsed,
}: {
  label:    string;
  docType:  DocType;
  onParsed: (doc: ParsedDoc) => void;
}) {
  const [dragging,   setDragging]   = useState(false);
  const [uploading,  setUploading]  = useState(false);
  const [error,      setError]      = useState("");

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError("");
      try {
        const fd = new FormData();
        fd.append("file", file);

        const resp = await fetch(`${API}/api/upload/${docType}`, {
          method: "POST",
          body:   fd,
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) throw new Error(data.error || "Upload failed");

        onParsed({ ...data, filename: file.name });
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [docType, onParsed]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) upload(file);
    },
    [upload]
  );

  return (
    <label
      className={`block border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-300
        ${dragging   ? "border-blue-400 bg-blue-500/10 shadow-[0_0_15px_rgba(59,130,246,0.3)]"  : "border-white/20 bg-white/5 hover:border-blue-500/50 hover:bg-white/10"}
        ${uploading  ? "opacity-60 pointer-events-none" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input
        type="file"
        className="hidden"
        accept=".pdf,image/jpeg,image/png"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
      />
      <div className="text-4xl mb-3 transition-transform transform group-hover:scale-110">{uploading ? "⏳" : "📁"}</div>
      <div className="font-medium text-slate-200">{label}</div>
      <div className="text-sm text-slate-400 mt-2">
        {uploading ? "AI is Parsing Document…" : "Drag & drop or browse"}
      </div>
      <div className="text-xs text-slate-500 mt-1 font-mono">PDF, JPG, PNG — max 20MB</div>
      {error && (
        <div className="mt-4 text-sm text-red-300 bg-red-900/40 border border-red-500/30 rounded px-3 py-2">{error}</div>
      )}
    </label>
  );
}


// ── Main page ──────────────────────────────────────────────────────────────

export default function UploadPage() {
  const router = useRouter();
  const [docs,     setDocs]     = useState<ParsedDoc[]>([]);
  const [running,  setRunning]  = useState(false);
  const [error,    setError]    = useState("");

  const addDoc = (doc: ParsedDoc) => {
    setDocs((prev) => [...prev, doc]);
  };
  const removeDoc = (i: number) => setDocs((prev) => prev.filter((_, j) => j !== i));

  const runPipeline = async () => {
    if (docs.length === 0) return;
    setRunning(true);
    setError("");

    try {
      const resp = await fetch(`${API}/api/pipeline/run`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          parsed_documents: docs.map((d) => ({ doc_type: d.doc_type, data: d.data })),
          session_id:       docs[0]?.session_id,
          ay:               "AY2024-25",
        }),
      });
      const result = await resp.json();
      if (!resp.ok || !result.success) throw new Error(result.error || "Pipeline failed");

      // Navigate to form viewer with session id
      router.push(`/form?session=${result.session_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Pipeline failed");
    } finally {
      setRunning(false);
    }
  };

  const hasForm16 = docs.some((d) => d.doc_type === "form16");

  return (
    <div className="min-h-screen pt-20 pb-12 relative overflow-hidden">
      {/* Dynamic Background */}
      <div className="absolute top-1/2 left-0 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl mix-blend-screen transform -translate-y-1/2" />
      <div className="absolute top-1/4 right-0 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl mix-blend-screen" />

      <div className="max-w-3xl mx-auto px-4 relative z-10 fade-in-up">
        {/* Header */}
        <div className="mb-12 text-center text-slate-200">
          <h1 className="text-4xl font-bold tracking-tight mb-3">Initialize Dashboard</h1>
          <p className="text-slate-400">
            Upload your documents — AI will strictly apply 2025 laws and prep your ITR-1.
          </p>
          <div className="mt-4 text-xs font-semibold text-blue-300 bg-blue-900/30 border border-blue-500/20 rounded-full px-5 py-2 inline-flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span>AY 2024-25 • STRICT NEW REGIME</span>
          </div>
        </div>

        {/* Upload zones */}
        <div className="space-y-8">
          <div className="glass-card p-6 rounded-2xl">
            <div className="text-sm font-semibold text-slate-200 mb-3 flex items-center">
              Form 16 <span className="text-red-400 ml-1">*</span>
              <span className="ml-auto text-xs text-slate-400 font-normal">REQUIRED</span>
            </div>
            <DropZone label="Upload Form 16 (Part A + B)" docType="form16" onParsed={addDoc} />
          </div>

          <div className="glass-card p-6 rounded-2xl">
            <div className="text-sm font-semibold text-slate-200 mb-3 flex items-center">
              Bank Statements
              <span className="ml-auto text-xs text-slate-400 font-normal">OPTIONAL</span>
            </div>
            <DropZone label="Upload Bank Statement(s)" docType="bank_statement" onParsed={addDoc} />
          </div>
        </div>

        {/* Parsed docs */}
        {docs.length > 0 && (
          <div className="mt-8 space-y-4">
            <div className="text-sm font-medium text-slate-300 flex items-center">
              <span className="bg-slate-800 text-xs px-2 py-1 rounded mr-2">{docs.length}</span> Ready for Pipeline
            </div>
            <div className="grid gap-3">
              {docs.map((doc, i) => (
                <FileCard key={i} doc={doc} onRemove={() => removeDoc(i)} />
              ))}
            </div>
          </div>
        )}

        {/* CTA */}
        {error && (
          <div className="mt-6 text-sm text-red-300 bg-red-900/30 border border-red-500/30 rounded-xl px-4 py-3 text-center">
            {error}
          </div>
        )}

        <button
          onClick={runPipeline}
          disabled={!hasForm16 || running}
          className="mt-8 w-full py-4 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-[0_0_20px_rgba(79,70,229,0.3)] font-bold text-lg
            hover:shadow-[0_0_30px_rgba(79,70,229,0.5)] disabled:from-slate-800 disabled:to-slate-800 disabled:text-slate-500 disabled:shadow-none disabled:cursor-not-allowed transition-all"
        >
          {running ? "Processing Architecture..." : "Generate Dashboard →"}
        </button>

        {!hasForm16 && docs.length > 0 && (
          <p className="text-sm text-center text-amber-400 mt-4 bg-amber-900/20 p-2 rounded-lg">
            ⚠ Form 16 is required to proceed
          </p>
        )}

        {running && (
          <div className="mt-8 glass-card border border-blue-500/30 rounded-xl p-6 space-y-5">
            <div className="text-sm font-bold text-blue-300 mb-4 flex items-center gap-3">
              <span className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"></span>
              MULTI-AGENT PIPELINE ENGAGED
            </div>
            <div className="space-y-4 text-sm font-mono text-slate-300">
              <div className="flex items-center gap-3 animate-pulse"><span className="text-green-400">✔</span> [VISION] Parsing visual geometry arrays...</div>
              <div className="flex items-center gap-3 animate-pulse" style={{ animationDelay: "500ms" }}><span className="text-green-400">✔</span> [ORCHESTRATOR] Aligning values to ITR-1 Schema...</div>
              <div className="flex items-center gap-3 animate-pulse" style={{ animationDelay: "1500ms" }}><span className="text-purple-400">⚡</span> [TAX AI] Enforcing Strict 2025 New Regime Algorithms...</div>
              <div className="flex items-center gap-3 animate-pulse" style={{ animationDelay: "2500ms" }}><span className="text-blue-400">⚡</span> [RAG AI] Cross-referencing findings against tax database...</div>
              <div className="flex items-center gap-3 animate-pulse" style={{ animationDelay: "3500ms" }}><span className="text-blue-400">⚡</span> [VERIFIER] Compiling Dashboard Audit Trail...</div>
            </div>
          </div>
        )}

        {/* What happens next */}
        <div className="mt-12 glass-card rounded-xl p-6">
          <div className="text-sm font-bold text-slate-300 mb-4 tracking-wider uppercase">Pipeline Execution Plan</div>
          <ol className="text-sm text-slate-400 space-y-3">
            {[
              "Synthesize salary, TDS, HRA from Form 16.",
              "Extract other sources of income from Bank Statements.",
              "Apply standard deduction and 87A rebate via New Tax Regime calculations.",
              "Verify every mapping against RAG memory for accuracy.",
              "Construct a unified Dashboard with high transparency explanations.",
            ].map((step, i) => (
              <li key={i} className="flex gap-3">
                <span className="text-blue-500 font-bold shrink-0">0{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
