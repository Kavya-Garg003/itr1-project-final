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
    conf >= 80 ? "text-green-600" : conf >= 50 ? "text-amber-600" : "text-red-600";

  return (
    <div className="border rounded-lg p-4 bg-white relative">
      <button
        onClick={onRemove}
        className="absolute top-2 right-2 text-gray-400 hover:text-gray-700 text-lg leading-none"
      >
        ×
      </button>
      <div className="flex items-start gap-3">
        <div className="text-2xl">{doc.doc_type === "form16" ? "📋" : "🏦"}</div>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{doc.filename}</div>
          <div className="text-xs text-gray-500 mt-0.5 capitalize">
            {doc.doc_type.replace("_", " ")}
          </div>
          <div className={`text-xs mt-1 font-medium ${confColor}`}>
            {conf}% confidence
          </div>
          {doc.warnings.length > 0 && (
            <div className="mt-2 space-y-1">
              {doc.warnings.map((w, i) => (
                <div key={i} className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">
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
      className={`block border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors
        ${dragging   ? "border-blue-400 bg-blue-50"  : "border-gray-200 hover:border-gray-300"}
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
      <div className="text-3xl mb-2">{uploading ? "⏳" : "📂"}</div>
      <div className="font-medium text-gray-700">{label}</div>
      <div className="text-sm text-gray-400 mt-1">
        {uploading ? "Parsing…" : "Drag & drop or click to browse"}
      </div>
      <div className="text-xs text-gray-400 mt-1">PDF, JPG, PNG — max 20MB</div>
      {error && (
        <div className="mt-3 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>
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
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-3xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="mb-10 text-center">
          <h1 className="text-3xl font-semibold text-gray-900">ITR-1 Auto-Fill</h1>
          <p className="text-gray-500 mt-2">
            Upload your documents — AI fills your ITR-1 Sahaj form automatically.
          </p>
          <div className="mt-3 text-xs text-gray-400 bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 inline-block">
            AY 2024-25 &nbsp;·&nbsp; For salaried individuals &nbsp;·&nbsp; Income up to ₹50 lakh
          </div>
        </div>

        {/* Upload zones */}
        <div className="space-y-4">
          <div>
            <div className="text-sm font-medium text-gray-700 mb-2">
              Form 16 <span className="text-red-500">*</span>
              <span className="ml-2 text-xs text-gray-400 font-normal">Required — from your employer</span>
            </div>
            <DropZone label="Upload Form 16 (Part A + B)" docType="form16" onParsed={addDoc} />
          </div>

          <div>
            <div className="text-sm font-medium text-gray-700 mb-2">
              Bank Statements
              <span className="ml-2 text-xs text-gray-400 font-normal">
                Optional — for interest income (80TTA, FD interest)
              </span>
            </div>
            <DropZone label="Upload Bank Statement(s)" docType="bank_statement" onParsed={addDoc} />
          </div>
        </div>

        {/* Parsed docs */}
        {docs.length > 0 && (
          <div className="mt-6 space-y-3">
            <div className="text-sm font-medium text-gray-700">Uploaded documents</div>
            {docs.map((doc, i) => (
              <FileCard key={i} doc={doc} onRemove={() => removeDoc(i)} />
            ))}
          </div>
        )}

        {/* CTA */}
        {error && (
          <div className="mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        <button
          onClick={runPipeline}
          disabled={!hasForm16 || running}
          className="mt-8 w-full py-3.5 rounded-xl bg-blue-600 text-white font-medium text-base
            hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {running ? "Analysing documents…" : "Fill My ITR-1 →"}
        </button>

        {!hasForm16 && docs.length > 0 && (
          <p className="text-xs text-center text-amber-600 mt-2">
            Form 16 is required to proceed
          </p>
        )}

        {/* What happens next */}
        <div className="mt-10 border rounded-xl p-5 bg-white">
          <div className="text-sm font-medium text-gray-700 mb-3">What the AI does</div>
          <ol className="text-sm text-gray-500 space-y-2">
            {[
              "Extracts salary, TDS, HRA, deductions from Form 16",
              "Extracts interest income from bank statements",
              "Compares old vs new tax regime — recommends the better one",
              "Fills all ITR-1 fields with source citations",
              "Validates for errors and flags low-confidence fields",
              "Explains every filled field in plain English",
            ].map((step, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-blue-400 font-medium shrink-0">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
