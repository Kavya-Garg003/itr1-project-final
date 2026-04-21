"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";

// ── Types ──────────────────────────────────────────────────────────────────

interface FieldConf {
  value:       number | string;
  confidence:  number;
  source:      string;
  explanation: string;
  flagged:     boolean;
  citation?:   string;
}

interface ITRData {
  itr1_form:        Record<string, unknown>;
  confidence_scores: Record<string, FieldConf>;
  validation_flags:  Array<{ field: string; severity: string; message: string; suggestion?: string }>;
  explanations:      Record<string, string>;
  regime_analysis:   Record<string, unknown>;
}

// ── Field row ──────────────────────────────────────────────────────────────

function FieldRow({
  label,
  fieldPath,
  value,
  conf,
  onEdit,
}: {
  label:    string;
  fieldPath: string;
  value:    string | number;
  conf?:    FieldConf;
  onEdit:   (field: string, label: string, val: string | number) => void;
}) {
  const confidence = conf?.confidence ?? 1;
  const pct        = Math.round(confidence * 100);
  const isAmount   = typeof value === "number";
  const display    = isAmount
    ? value === 0 ? "—" : `₹${Number(value).toLocaleString("en-IN")}`
    : String(value || "—");

  const barColor =
    pct >= 80 ? "bg-green-400"
    : pct >= 50 ? "bg-amber-400"
    : "bg-red-400";

  const sourceLabel: Record<string, string> = {
    form16:          "Form 16",
    bank_statement:  "Bank stmt",
    computed:        "Computed",
    rag_inference:   "AI inferred",
    manual:          "Manual",
    missing:         "Missing",
  };

  return (
    <div className={`flex items-start gap-4 py-4 border-b border-white/10 last:border-b-0 ${conf?.flagged ? "bg-red-900/20 px-3 rounded-lg -mx-3" : ""}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-slate-300 font-medium truncate">{label}</span>
          {conf?.flagged && (
            <span className="text-xs text-red-600 bg-red-100 rounded px-1.5 py-0.5 shrink-0">
              Review needed
            </span>
          )}
        </div>
        {conf?.explanation && (
          <div className="text-xs text-gray-400 mt-0.5 truncate">{conf.explanation}</div>
        )}
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {/* Confidence bar */}
          {conf && (
          <div className="w-24 flex items-center gap-2 hide-on-print">
            <div className="flex-1 h-2 bg-slate-800/50 rounded-full overflow-hidden border border-white/5">
              <div className={`h-full ${barColor} rounded-full`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-slate-400 w-8 text-right font-mono">{pct}%</span>
          </div>
        )}

        {/* Source badge */}
        {conf?.source && (
          <span className="text-[10px] uppercase font-bold tracking-wider text-blue-300 bg-blue-900/30 border border-blue-500/20 rounded px-2 py-1 hidden sm:block">
            {sourceLabel[conf.source] || conf.source}
          </span>
        )}

        {/* Value */}
        <span className={`text-sm font-semibold w-32 text-right ${!value || value === 0 ? "text-slate-600" : "text-slate-100"}`}>
          {display}
        </span>

        {/* Edit button */}
        <button
          onClick={() => onEdit(fieldPath, label, value)}
          className="text-slate-500 hover:text-blue-400 transition-colors text-sm hide-on-print ml-2"
          title="Edit"
        >
          ✎
        </button>
      </div>
    </div>
  );
}

// ── Section card ──────────────────────────────────────────────────────────

function SectionCard({
  title,
  emoji,
  children,
  total,
}: {
  title:    string;
  emoji:    string;
  children: React.ReactNode;
  total?:   { label: string; value: number };
}) {
  return (
    <div className="glass-card overflow-hidden mb-6">
      <div className="px-6 py-4 glass-header flex items-center gap-3">
        <span className="text-xl">{emoji}</span>
        <span className="font-semibold text-slate-100 text-sm tracking-wide uppercase">{title}</span>
      </div>
      <div className="px-6 py-2">{children}</div>
      {total && (
        <div className="px-6 py-4 border-t border-white/10 bg-blue-900/10 flex justify-between items-center">
          <span className="text-sm font-semibold text-blue-300 uppercase tracking-widest">{total.label}</span>
          <span className="text-lg font-bold text-blue-100">
            ₹{total.value.toLocaleString("en-IN")}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Edit modal ─────────────────────────────────────────────────────────────

function EditModal({
  field,
  label,
  value,
  sessionId,
  onClose,
  onSaved,
}: {
  field:     string;
  label:     string;
  value:     string | number;
  sessionId: string;
  onClose:   () => void;
  onSaved:   () => void;
}) {
  const [val,    setVal]    = useState(String(value));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    await fetch(`${API}/api/pipeline/update-field`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ session_id: sessionId, field_path: field, value: Number(val) || val, reason }),
    });
    setSaving(false);
    onSaved();
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="glass-card w-full max-w-md p-8 relative">
        <div className="font-bold text-lg text-slate-100 mb-2">{label}</div>
        <div className="text-xs text-blue-400 mb-6 font-mono tracking-wider">{field}</div>
        <input
          type="text"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 mb-4 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
        />
        <input
          type="text"
          placeholder="Reason for change required by audit trail"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 mb-6 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
        />
        <div className="flex gap-4">
          <button onClick={onClose} className="flex-1 py-3 justify-center rounded-xl border border-white/10 text-sm text-slate-300 font-medium hover:bg-white/5 transition-colors">
            Cancel
          </button>
          <button onClick={save} disabled={saving} className="flex-1 py-3 justify-center rounded-xl bg-blue-600 font-medium text-white text-sm hover:bg-blue-700 shadow-[0_0_15px_rgba(37,99,235,0.3)] disabled:opacity-50 transition-all">
            {saving ? "Updating..." : "Save Override"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Main Form Viewer ───────────────────────────────────────────────────────

function FormPageInner() {
  const params    = useSearchParams();
  const sessionId = params.get("session") || "";

  const [data,    setData]    = useState<ITRData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editTarget, setEditTarget] = useState<{ field: string; label: string; value: string | number } | null>(null);

  const loadData = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const resp = await fetch(`${API}/api/pipeline/${sessionId}`);
      const json = await resp.json();
      setData(json);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [sessionId]);

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center text-gray-400">
      Loading your filled ITR-1…
    </div>
  );
  if (!data) return (
    <div className="min-h-screen flex items-center justify-center text-red-500">
      Session not found. Start again.
    </div>
  );

  const form   = data.itr1_form as Record<string, Record<string, number | string>>;
  const conf   = data.confidence_scores;
  const flags  = data.validation_flags;
  const tc     = form.tax_computation as Record<string, number | string>;
  const sal    = form.salary_income as Record<string, number | string>;
  const ded    = form.deductions as Record<string, number | string>;
  const os     = form.other_sources as Record<string, number | string>;
  const regime = String(tc?.regime || "new");

  const F = (path: string) => conf[path];

  return (
    <div className="min-h-screen pt-20 pb-16 relative overflow-hidden">
      {/* Dynamic Background */}
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-600/10 rounded-full blur-[100px] mix-blend-screen pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-purple-600/10 rounded-full blur-[100px] mix-blend-screen pointer-events-none" />

      <div className="max-w-4xl mx-auto px-4 relative z-10 fade-in-up">
        {/* Header */}
        <div className="glass-card mb-8 p-6 flex flex-col md:flex-row items-start md:items-center justify-between rounded-2xl">
          <div>
            <h1 className="text-3xl font-bold text-slate-100 flex items-center">
              ITR-1 (Sahaj) Dashboard
              <span className="ml-4 text-xs font-semibold bg-green-500/20 text-green-400 px-3 py-1 rounded-full border border-green-500/30">VERIFIED</span>
            </h1>
            <div className="text-slate-400 mt-2 font-medium tracking-wide">
              AY 2024-25 <span className="mx-2">•</span> 2025 NEW REGIME STRICT
            </div>
          </div>
          <div className="flex gap-3 hide-on-print mt-4 md:mt-0">
            <button
              onClick={() => window.print()}
              className="px-5 py-2.5 rounded-xl border border-white/10 text-slate-300 text-sm font-semibold hover:bg-white/5 transition-colors"
            >
              Print PDF
            </button>
            <a
              href={`${API}/api/pipeline/export/${sessionId}`}
              target="_blank"
              className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-white text-sm font-bold shadow-[0_0_15px_rgba(79,70,229,0.3)] hover:shadow-[0_0_25px_rgba(79,70,229,0.5)] transition-all"
            >
              Export JSON
            </a>
          </div>
        </div>

        {flags.length > 0 && (
          <div className="mb-8 space-y-3">
            {flags.map((f, i) => (
              <div key={i} className={`rounded-xl px-5 py-4 text-sm border flex flex-col
                ${f.severity === "error"   ? "glass-card border-red-500/30 text-red-200 bg-red-900/10"
                : f.severity === "warning" ? "glass-card border-amber-500/30 text-amber-200 bg-amber-900/10"
                : "glass-card border-blue-500/30 text-blue-200 bg-blue-900/10"}`}>
                <div><span className="font-bold uppercase tracking-wider text-xs mr-2">{f.severity}:</span> {f.message}</div>
                {f.suggestion && <div className="text-xs mt-2 opacity-70 border-t border-white/10 pt-2 font-mono">→ {f.suggestion}</div>}
              </div>
            ))}
          </div>
        )}

        <div className="space-y-4">
          {/* Salary Income */}
          <SectionCard title="Salary Income (Schedule S)" emoji="💼"
            total={{ label: "Taxable salary", value: Number(sal?.taxable_salary || 0) }}>
            <FieldRow label="Gross salary" fieldPath="salary_income.gross_salary"
              value={Number(sal?.gross_salary || 0)} conf={F("salary_income.gross_salary")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="HRA exemption [10(13A)]" fieldPath="salary_income.allowances_exempt_10_13a"
              value={Number(sal?.allowances_exempt_10_13a || 0)} conf={F("salary_income.allowances_exempt_10_13a")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Standard deduction [16(ia)]" fieldPath="salary_income.standard_deduction_16ia"
              value={Number(sal?.standard_deduction_16ia || 0)} conf={F("salary_income.standard_deduction_16ia")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Professional tax [16(iii)]" fieldPath="salary_income.professional_tax_16iii"
              value={Number(sal?.professional_tax_16iii || 0)} conf={F("salary_income.professional_tax_16iii")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
          </SectionCard>

          {/* Other Sources */}
          <SectionCard title="Other Sources Income (Schedule OS)" emoji="🏦"
            total={{ label: "Total other sources", value: Number(os?.total_other_sources || 0) }}>
            <FieldRow label="Savings bank interest" fieldPath="other_sources.savings_bank_interest"
              value={Number(os?.savings_bank_interest || 0)} conf={F("other_sources.savings_bank_interest")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="FD interest" fieldPath="other_sources.fd_interest"
              value={Number(os?.fd_interest || 0)} conf={F("other_sources.fd_interest")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
          </SectionCard>

          {/* Deductions */}
          <SectionCard title="Deductions (Chapter VI-A)" emoji="🧾"
            total={{ label: "Total deductions", value: Number(ded?.total_deductions || 0) }}>
            <FieldRow label="Section 80C (LIC, PPF, ELSS…)" fieldPath="deductions.sec_80c"
              value={Number(ded?.sec_80c || 0)} conf={F("deductions.sec_80c")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Section 80D (Health insurance)" fieldPath="deductions.sec_80d"
              value={Number(ded?.sec_80d || 0)} conf={F("deductions.sec_80d")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Section 80TTA (Savings interest)" fieldPath="deductions.sec_80tta"
              value={Number(ded?.sec_80tta || 0)} conf={F("deductions.sec_80tta")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Section 80CCD(2) (Employer NPS)" fieldPath="deductions.sec_80ccd_2"
              value={Number(ded?.sec_80ccd_2 || 0)} conf={F("deductions.sec_80ccd_2")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
          </SectionCard>

          {/* Tax computation */}
          <SectionCard title={`Tax Computation (${regime.toUpperCase()} REGIME)`} emoji="🧮">
            <FieldRow label="Gross total income" fieldPath="tax_computation.gross_total_income"
              value={Number(tc?.gross_total_income || 0)} conf={F("tax_computation.gross_total_income")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Taxable income" fieldPath="tax_computation.taxable_income"
              value={Number(tc?.taxable_income || 0)} conf={F("tax_computation.taxable_income")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Tax before rebate" fieldPath="tax_computation.tax_before_rebate"
              value={Number(tc?.tax_before_rebate || 0)}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Rebate u/s 87A" fieldPath="tax_computation.rebate_87a"
              value={Number(tc?.rebate_87a || 0)} conf={F("tax_computation.rebate_87a")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Health & education cess (4%)" fieldPath="tax_computation.health_education_cess"
              value={Number(tc?.health_education_cess || 0)}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="Total tax liability" fieldPath="tax_computation.total_tax_liability"
              value={Number(tc?.total_tax_liability || 0)}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
            <FieldRow label="TDS already deducted" fieldPath="tds_details.0.tds_deducted"
              value={Number(tc?.tds_deducted || 0)} conf={F("tds_details.0.tds_deducted")}
              onEdit={(f, l, v) => setEditTarget({ field: f, label: l, value: v })} />
          </SectionCard>

          {/* Final result */}
          <div className={`glass-card p-8 text-center flex flex-col items-center justify-center border-t-4
            ${Number(tc?.refund || 0) > 0 ? "border-t-green-500" : "border-t-amber-500"}`}>
            {Number(tc?.refund || 0) > 0 ? (
              <>
                <div className="text-sm font-bold text-green-400 uppercase tracking-widest mb-2">Estimated Refund</div>
                <div className="text-4xl md:text-5xl font-bold text-slate-100">
                  ₹{Number(tc?.refund || 0).toLocaleString("en-IN")}
                </div>
                <div className="text-sm mt-3 text-slate-400">Directly credited to your registered bank account</div>
              </>
            ) : (
              <>
                <div className="text-sm font-bold text-amber-500 uppercase tracking-widest mb-2">Net Tax Payable</div>
                <div className="text-4xl md:text-5xl font-bold text-slate-100">
                  ₹{Number(tc?.tax_payable || 0).toLocaleString("en-IN")}
                </div>
                <div className="text-sm mt-3 text-slate-400">Please clear dues before filing deadline</div>
              </>
            )}
          </div>
        </div>

        {/* Chat Float */}
        <div className="mt-12 flex justify-center hide-on-print">
          <a
            href={`/chat?session=${sessionId}`}
            className="group relative inline-flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-purple-600 to-indigo-600 rounded-full text-white font-bold text-lg shadow-[0_0_20px_rgba(147,51,234,0.3)] hover:shadow-[0_0_40px_rgba(147,51,234,0.6)] transition-all transform hover:-translate-y-1"
          >
             <span className="text-2xl">🤖</span>
             <span>Chat with Contextual Tax AI</span>
             <span className="group-hover:translate-x-2 transition-transform duration-300">→</span>
          </a>
        </div>
      </div>

      {/* Edit modal */}
      {editTarget && (
        <EditModal
          {...editTarget}
          sessionId={sessionId}
          onClose={() => setEditTarget(null)}
          onSaved={loadData}
        />
      )}
    </div>
  );
}

export default function FormPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">
        Loading your form...
      </div>
    }>
      <FormPageInner />
    </Suspense>
  );
}
