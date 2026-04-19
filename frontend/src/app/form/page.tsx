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
    <div className={`flex items-start gap-3 py-3 border-b last:border-b-0 ${conf?.flagged ? "bg-red-50" : ""}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-gray-600 truncate">{label}</span>
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
          <div className="w-20 flex items-center gap-1.5">
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${barColor} rounded-full`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-gray-400 w-7 text-right">{pct}%</span>
          </div>
        )}

        {/* Source badge */}
        {conf?.source && (
          <span className="text-xs text-gray-400 bg-gray-100 rounded px-1.5 py-0.5 hidden sm:block">
            {sourceLabel[conf.source] || conf.source}
          </span>
        )}

        {/* Value */}
        <span className={`text-sm font-medium w-28 text-right ${!value || value === 0 ? "text-gray-300" : "text-gray-900"}`}>
          {display}
        </span>

        {/* Edit button */}
        <button
          onClick={() => onEdit(fieldPath, label, value)}
          className="text-gray-300 hover:text-blue-500 text-sm"
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
    <div className="border rounded-xl bg-white overflow-hidden">
      <div className="px-5 py-3.5 bg-gray-50 border-b flex items-center gap-2">
        <span>{emoji}</span>
        <span className="font-medium text-gray-800 text-sm">{title}</span>
      </div>
      <div className="px-5">{children}</div>
      {total && (
        <div className="px-5 py-3 border-t bg-blue-50 flex justify-between items-center">
          <span className="text-sm font-medium text-blue-800">{total.label}</span>
          <span className="text-base font-semibold text-blue-900">
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
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
        <div className="font-medium text-gray-900 mb-1">{label}</div>
        <div className="text-xs text-gray-400 mb-4 font-mono">{field}</div>
        <input
          type="text"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <input
          type="text"
          placeholder="Reason for change (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={save} disabled={saving} className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
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
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-10">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Your ITR-1 (Sahaj)</h1>
            <div className="text-sm text-gray-400 mt-0.5">AY 2024-25 · Auto-filled by AI</div>
          </div>
          <a
            href={`${API}/api/pipeline/export/${sessionId}`}
            target="_blank"
            className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
          >
            Export JSON
          </a>
        </div>

        {/* Validation flags */}
        {flags.length > 0 && (
          <div className="mb-5 space-y-2">
            {flags.map((f, i) => (
              <div key={i} className={`rounded-lg px-4 py-3 text-sm border
                ${f.severity === "error"   ? "bg-red-50 border-red-200 text-red-800"
                : f.severity === "warning" ? "bg-amber-50 border-amber-200 text-amber-800"
                : "bg-blue-50 border-blue-200 text-blue-800"}`}>
                <span className="font-medium capitalize">{f.severity}:</span> {f.message}
                {f.suggestion && <div className="text-xs mt-1 opacity-80">→ {f.suggestion}</div>}
              </div>
            ))}
          </div>
        )}

        {/* Regime recommendation */}
        {data.explanations?.regime_recommendation && (
          <div className="mb-5 bg-green-50 border border-green-200 rounded-xl px-5 py-4 text-sm text-green-800">
            <div className="font-medium mb-1">💡 Regime recommendation</div>
            {data.explanations.regime_recommendation}
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
          <div className={`rounded-xl px-6 py-5 text-center font-medium border
            ${Number(tc?.refund || 0) > 0
              ? "bg-green-50 border-green-200 text-green-900"
              : "bg-amber-50 border-amber-200 text-amber-900"}`}>
            {Number(tc?.refund || 0) > 0 ? (
              <>
                <div className="text-2xl font-bold">
                  Refund: ₹{Number(tc?.refund || 0).toLocaleString("en-IN")}
                </div>
                <div className="text-sm mt-1 opacity-70">Expected refund to your bank account</div>
              </>
            ) : (
              <>
                <div className="text-2xl font-bold">
                  Tax payable: ₹{Number(tc?.tax_payable || 0).toLocaleString("en-IN")}
                </div>
                <div className="text-sm mt-1 opacity-70">Pay before filing deadline</div>
              </>
            )}
          </div>
        </div>

        {/* Chat button */}
        <div className="mt-6 text-center">
          <a
            href={`/chat?session=${sessionId}`}
            className="text-sm text-blue-600 hover:underline"
          >
            Ask a question about your return →
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
