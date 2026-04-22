"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";

// ── Types ──────────────────────────────────────────────────────────────────

interface FieldConf {
  value: number | string;
  confidence: number;
  source: string;
  explanation: string;
  flagged: boolean;
  citation?: string;
}

interface ITRData {
  itr1_form: Record<string, unknown>;
  confidence_scores: Record<string, FieldConf>;
  validation_flags: Array<{ field: string; severity: string; message: string; suggestion?: string }>;
  explanations: Record<string, string>;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const SRC: Record<string, string> = {
  form16: "Form 16", bank_statement: "Bank stmt",
  computed: "Computed", manual: "Manual", missing: "Missing", rag_inference: "AI",
};

function rupee(v: number | undefined | null): string {
  if (!v || v === 0) return "—";
  return `₹${Number(v).toLocaleString("en-IN")}`;
}

// ── Field Row ──────────────────────────────────────────────────────────────

function FR({
  label, path, value, conf, onEdit, indent = false,
}: {
  label: string; path: string; value: number | string;
  conf?: FieldConf; onEdit: (f: string, l: string, v: number | string) => void;
  indent?: boolean;
}) {
  const pct = Math.round((conf?.confidence ?? 1) * 100);
  const bar = pct >= 80 ? "bg-green-400" : pct >= 50 ? "bg-amber-400" : "bg-red-400";
  const isNum = typeof value === "number";
  const display = isNum ? rupee(value as number) : String(value || "—");

  return (
    <div className={`flex items-start gap-4 py-3 border-b border-white/5 last:border-0
      ${conf?.flagged ? "bg-red-900/10 -mx-3 px-3 rounded-lg" : ""}
      ${indent ? "pl-5" : ""}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className={`text-sm truncate ${indent ? "text-slate-400" : "text-slate-300 font-medium"}`}>{label}</span>
          {conf?.flagged && (
            <span className="text-[10px] font-bold text-red-400 bg-red-900/30 border border-red-500/30 rounded px-1.5 shrink-0">REVIEW</span>
          )}
        </div>
        {conf?.explanation && (
          <div className="text-xs text-slate-500 mt-0.5 truncate">{conf.explanation}</div>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {conf && (
          <div className="w-20 flex items-center gap-1.5 hide-on-print">
            <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className={`h-full ${bar} rounded-full`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[10px] text-slate-500 w-7 text-right font-mono">{pct}%</span>
          </div>
        )}
        {conf?.source && (
          <span className="text-[9px] uppercase font-bold tracking-wider text-blue-300/70 bg-blue-900/20 border border-blue-500/10 rounded px-1.5 py-0.5 hidden md:block">
            {SRC[conf.source] || conf.source}
          </span>
        )}
        <span className={`text-sm font-semibold w-32 text-right tabular-nums
          ${(!value || value === 0) ? "text-slate-600" : "text-slate-100"}`}>
          {display}
        </span>
        <button onClick={() => onEdit(path, label, value)}
          className="text-slate-600 hover:text-blue-400 transition-colors text-sm hide-on-print ml-1" title="Edit">✎</button>
      </div>
    </div>
  );
}

// ── Section Card ──────────────────────────────────────────────────────────

function SC({ title, emoji, children, total, note }: {
  title: string; emoji: string; children: React.ReactNode;
  total?: { label: string; value: number }; note?: string;
}) {
  return (
    <div className="glass-card overflow-hidden mb-4">
      <div className="px-6 py-3.5 glass-header flex items-center gap-2">
        <span>{emoji}</span>
        <span className="font-semibold text-slate-100 text-xs tracking-wider uppercase">{title}</span>
        {note && <span className="ml-auto text-[10px] text-slate-500 font-normal">{note}</span>}
      </div>
      <div className="px-6 py-1">{children}</div>
      {total && (
        <div className="px-6 py-3 border-t border-white/10 bg-blue-900/10 flex justify-between items-center">
          <span className="text-xs font-bold text-blue-300 uppercase tracking-wider">{total.label}</span>
          <span className="text-base font-bold text-blue-100 tabular-nums">{rupee(total.value)}</span>
        </div>
      )}
    </div>
  );
}

// ── Subtotal Row ──────────────────────────────────────────────────────────

function SubTotal({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between items-center py-2.5 border-b border-dashed border-white/10">
      <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">{label}</span>
      <span className="text-sm font-bold text-slate-200 tabular-nums">{rupee(value)}</span>
    </div>
  );
}

// ── Edit Modal ────────────────────────────────────────────────────────────

function EditModal({ field, label, value, sessionId, onClose, onSaved }: {
  field: string; label: string; value: number | string;
  sessionId: string; onClose: () => void; onSaved: () => void;
}) {
  const [val, setVal] = useState(String(value));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    await fetch(`${API}/api/pipeline/update-field`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, field_path: field,
        value: Number(val) || val, reason }),
    });
    setSaving(false); onSaved(); onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="glass-card w-full max-w-md p-8">
        <div className="font-bold text-lg text-slate-100 mb-1">{label}</div>
        <div className="text-xs text-blue-400 mb-5 font-mono">{field}</div>
        <input type="text" value={val} onChange={e => setVal(e.target.value)}
          className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 mb-3
            focus:outline-none focus:border-blue-500 transition-colors" />
        <input type="text" placeholder="Reason for change" value={reason}
          onChange={e => setReason(e.target.value)}
          className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 mb-5
            focus:outline-none focus:border-blue-500 transition-colors" />
        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 py-3 rounded-xl border border-white/10 text-slate-300 text-sm hover:bg-white/5 transition-colors">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Main Form Page ─────────────────────────────────────────────────────────

function FormPageInner() {
  const params    = useSearchParams();
  const sessionId = params.get("session") || "";
  const [data, setData]       = useState<ITRData | null>(null);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit]       = useState<{ field: string; label: string; value: number | string } | null>(null);

  const load = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/pipeline/${sessionId}`);
      setData(await r.json());
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [sessionId]);

  if (loading) return <div className="min-h-screen flex items-center justify-center text-slate-400">Loading ITR-1…</div>;
  if (!data)   return <div className="min-h-screen flex items-center justify-center text-red-400">Session not found.</div>;

  const form = data.itr1_form as Record<string, Record<string, number | string>>;
  const cf   = data.confidence_scores;
  const flags = data.validation_flags;
  const exp  = data.explanations;

  const pi  = form.personal_info  || {};
  const sal = form.salary_income  || {};
  const hp  = form.house_property || {};
  const os  = form.other_sources  || {};
  const ded = form.deductions     || {};
  const tc  = form.tax_computation || {};
  const tds = (form.tds_details as unknown as Array<Record<string, number | string>>) || [];
  const tds0 = tds[0] || {};

  const F = (p: string) => cf[p];
  const E = (f: string, l: string, v: number | string) => setEdit({ field: f, label: l, value: v });

  return (
    <div className="min-h-screen pt-20 pb-16 relative overflow-hidden">
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-600/10 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-purple-600/10 rounded-full blur-[100px] pointer-events-none" />

      <div className="max-w-4xl mx-auto px-4 relative z-10">

        {/* Header */}
        <div className="glass-card mb-6 p-6 flex flex-col md:flex-row items-start md:items-center justify-between rounded-2xl">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-100 flex items-center gap-3">
              ITR-1 (Sahaj) Dashboard
              <span className="text-xs font-semibold bg-green-500/20 text-green-400 px-3 py-1 rounded-full border border-green-500/30">AI-FILLED</span>
            </h1>
            <div className="text-slate-400 mt-1.5 text-sm">
              AY {String(pi.assessment_year || "2024-25")} · New Tax Regime 2025
              {pi.first_name && <span className="ml-3 text-slate-300 font-medium">· {[pi.first_name, pi.middle_name, pi.last_name].filter(Boolean).join(" ")}</span>}
              {pi.pan && <span className="ml-2 font-mono text-blue-400 text-xs">{String(pi.pan)}</span>}
            </div>
          </div>
          <div className="flex gap-2 mt-4 md:mt-0 flex-wrap hide-on-print">
            <button onClick={() => window.print()}
              className="px-4 py-2 rounded-xl border border-white/10 text-slate-300 text-sm hover:bg-white/5 transition-colors">Print PDF</button>
            <button onClick={() => window.open(`${API}/api/pipeline/export/${sessionId}?format=excel`, "_blank")}
              className="px-4 py-2 rounded-xl bg-green-700/80 text-white text-sm font-semibold hover:bg-green-600 transition-colors">↓ Excel</button>
            <a href={`${API}/api/pipeline/export/${sessionId}`} target="_blank"
              className="px-4 py-2 rounded-xl bg-blue-700/80 text-white text-sm font-semibold hover:bg-blue-600 transition-colors">↓ JSON</a>
          </div>
        </div>

        {/* Validation Flags */}
        {flags.length > 0 && (
          <div className="mb-5 space-y-2">
            {flags.map((f, i) => (
              <div key={i} className={`glass-card px-5 py-3 text-sm flex flex-col rounded-xl border
                ${f.severity === "error"   ? "border-red-500/30 text-red-200 bg-red-900/10"
                : f.severity === "warning" ? "border-amber-500/30 text-amber-200 bg-amber-900/10"
                : "border-blue-500/30 text-blue-200 bg-blue-900/10"}`}>
                <span><b className="uppercase text-xs tracking-wider mr-2">{f.severity}</b>{f.message}</span>
                {f.suggestion && <span className="text-xs mt-1 opacity-70 border-t border-white/10 pt-1 font-mono">→ {f.suggestion}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Regime explanation */}
        {exp.regime && (
          <div className="glass-card mb-5 px-5 py-3 text-sm text-slate-300 border border-blue-500/20 rounded-xl">
            <span className="font-bold text-blue-400 mr-2">ℹ Regime:</span>{exp.regime}
          </div>
        )}

        {/* ── PART A: PERSONAL INFO ───────────────────────────────────────── */}
        <SC title="Part A — Personal Information" emoji="🪪">
          <FR label="PAN"              path="personal_info.pan"        value={String(pi.pan || "")}        conf={F("personal_info.pan")}        onEdit={E} />
          <FR label="First name"       path="personal_info.first_name"  value={String(pi.first_name || "")}  conf={F("personal_info.first_name")}  onEdit={E} />
          <FR label="Middle name"      path="personal_info.middle_name" value={String(pi.middle_name || "")} onEdit={E} />
          <FR label="Last / Surname"   path="personal_info.last_name"   value={String(pi.last_name || "")}   onEdit={E} />
          <FR label="Date of birth"    path="personal_info.dob"         value={String(pi.dob || "")}         onEdit={E} />
          <FR label="Aadhaar number"   path="personal_info.aadhaar"     value={String(pi.aadhaar || "")}     onEdit={E} />
          <FR label="Mobile"           path="personal_info.mobile"      value={String(pi.mobile || "")}      onEdit={E} />
          <FR label="Email"            path="personal_info.email"       value={String(pi.email || "")}       onEdit={E} />
          <FR label="Address (flat/door/block)" path="personal_info.address_flat"   value={String(pi.address_flat || "")}   onEdit={E} />
          <FR label="Road / Street"    path="personal_info.address_street" value={String(pi.address_street || "")} onEdit={E} />
          <FR label="City"             path="personal_info.address_city"  value={String(pi.address_city || "")}  onEdit={E} />
          <FR label="State"            path="personal_info.address_state" value={String(pi.address_state || "")} onEdit={E} />
          <FR label="PIN code"         path="personal_info.address_pin"   value={String(pi.address_pin || "")}   onEdit={E} />
          <FR label="Bank account no." path="personal_info.bank_account_number" value={String(pi.bank_account_number || pi.bank_account || "")} onEdit={E} />
          <FR label="IFSC code"        path="personal_info.bank_ifsc"    value={String(pi.bank_ifsc || "")}    onEdit={E} />
          <FR label="Bank name"        path="personal_info.bank_name"    value={String(pi.bank_name || "")}    onEdit={E} />
        </SC>

        {/* ── SCHEDULE S: SALARY INCOME ─────────────────────────────────── */}
        <SC title="Schedule S — Salary Income" emoji="💼"
          total={{ label: "(v) Income from salary", value: Number(sal.taxable_salary || 0) }}>

          {/* Gross salary breakdown */}
          <FR label="(a) Salary as per Sec 17(1)"         path="salary_income.salary_as_per_17_1"  value={Number(sal.salary_as_per_17_1 || 0)}  conf={F("salary_income.salary_as_per_17_1")}  onEdit={E} indent />
          <FR label="(b) Perquisites u/s 17(2)"           path="salary_income.perquisites_17_2"    value={Number(sal.perquisites_17_2 || 0)}    conf={F("salary_income.perquisites_17_2")}    onEdit={E} indent />
          <FR label="(c) Profits in lieu u/s 17(3)"       path="salary_income.profits_17_3"        value={Number(sal.profits_17_3 || 0)}        conf={F("salary_income.profits_17_3")}        onEdit={E} indent />
          <SubTotal label="(i) Gross Salary = a+b+c"       value={Number(sal.gross_salary || 0)} />

          {/* Sec 10 exemptions */}
          <FR label="Less: HRA exemption [10(13A)]"       path="salary_income.allowances_exempt_10_13a" value={Number(sal.allowances_exempt_10_13a || 0)} conf={F("salary_income.allowances_exempt_10_13a")} onEdit={E} indent />
          <FR label="Less: LTA [10(10)]"                  path="salary_income.allowances_exempt_10_10"  value={Number(sal.allowances_exempt_10_10 || 0)}  conf={F("salary_income.allowances_exempt_10_10")}  onEdit={E} indent />
          <FR label="Less: Other Sec 10 exemptions"       path="salary_income.allowances_exempt_other"  value={Number(sal.allowances_exempt_other || 0)}  onEdit={E} indent />
          <SubTotal label="(ii) Total Sec 10 exemptions"   value={Number(sal.total_exempt_allowances || 0)} />
          <SubTotal label="(iii) Net Salary = (i)−(ii)"    value={Number(sal.net_salary || 0)} />

          {/* Sec 16 deductions */}
          <FR label="Less: Std deduction [16(ia)] ₹50,000" path="salary_income.standard_deduction_16ia"     value={Number(sal.standard_deduction_16ia || 0)}     conf={F("salary_income.standard_deduction_16ia")}     onEdit={E} indent />
          <FR label="Less: Entertainment allowance [16(ii)]" path="salary_income.entertainment_allowance_16ii" value={Number(sal.entertainment_allowance_16ii || 0)} conf={F("salary_income.entertainment_allowance_16ii")} onEdit={E} indent />
          <FR label="Less: Professional tax [16(iii)]"     path="salary_income.professional_tax_16iii"       value={Number(sal.professional_tax_16iii || 0)}       conf={F("salary_income.professional_tax_16iii")}       onEdit={E} indent />
          <SubTotal label="(iv) Total Sec 16 deductions"    value={Number(sal.total_sec16_deductions || 0)} />
        </SC>

        {/* ── SCHEDULE HP: HOUSE PROPERTY ────────────────────────────────── */}
        <SC title="Schedule HP — House Property Income" emoji="🏠"
          total={{ label: "Income / (Loss) from HP", value: Number(hp.total_income_hp || 0) }}>
          <FR label="Annual letable value"            path="house_property.annual_value"          value={Number(hp.annual_value || 0)}            onEdit={E} />
          <FR label="Less: Municipal taxes paid"      path="house_property.municipal_tax_paid"    value={Number(hp.municipal_tax_paid || 0)}      onEdit={E} indent />
          <FR label="Net annual value"                path="house_property.net_annual_value"      value={Number(hp.net_annual_value || 0)}        onEdit={E} />
          <FR label="Less: 30% standard deduction"   path="house_property.standard_deduction_30pct" value={Number(hp.standard_deduction_30pct || 0)} onEdit={E} indent />
          <FR label="Less: Interest on home loan [24(b)]" path="house_property.interest_on_loan_24b" value={Number(hp.interest_on_loan_24b || 0)} onEdit={E} indent />
        </SC>

        {/* ── SCHEDULE OS: OTHER SOURCES ─────────────────────────────────── */}
        <SC title="Schedule OS — Other Sources Income" emoji="🏦"
          total={{ label: "Total Other Sources Income", value: Number(os.total_other_sources || 0) }}>
          <FR label="Interest — Savings bank (80TTA applies)" path="other_sources.savings_bank_interest" value={Number(os.savings_bank_interest || 0)} conf={F("other_sources.savings_bank_interest")} onEdit={E} />
          <FR label="Interest — FD / RD / Bonds"       path="other_sources.fd_interest"          value={Number(os.fd_interest || 0)}          conf={F("other_sources.fd_interest")}          onEdit={E} />
          <FR label="Interest — Recurring Deposit"     path="other_sources.recurring_deposit"    value={Number(os.recurring_deposit || 0)}    onEdit={E} />
          <FR label="Family Pension"                   path="other_sources.family_pension"       value={Number(os.family_pension || 0)}       onEdit={E} />
          <FR label="Dividends"                        path="other_sources.dividends"            value={Number(os.dividends || 0)}            onEdit={E} />
          <FR label="Other income"                     path="other_sources.other_income"         value={Number(os.other_income || 0)}         onEdit={E} />
        </SC>

        {/* ── GROSS TOTAL INCOME ─────────────────────────────────────────── */}
        <div className="glass-card mb-4 px-6 py-4 flex justify-between items-center border border-blue-500/20">
          <span className="font-bold text-slate-200 text-sm uppercase tracking-wider">Gross Total Income (GTI)</span>
          <span className="text-xl font-bold text-blue-300 tabular-nums">{rupee(Number(tc.gross_total_income || 0))}</span>
        </div>

        {/* ── CHAPTER VI-A DEDUCTIONS ────────────────────────────────────── */}
        <SC title="Chapter VI-A — Deductions" emoji="🧾"
          note="New regime 2025: only 80CCD(2) deductible"
          total={{ label: "Total Deductions (new regime)", value: Number(ded.total_deductions || 0) }}>
          <FR label="80CCD(2) — Employer NPS contribution ✓ new regime" path="deductions.sec_80ccd_2" value={Number(ded.sec_80ccd_2 || 0)} conf={F("deductions.sec_80ccd_2")} onEdit={E} />
          <div className="text-xs text-slate-600 px-1 py-2 border-b border-white/5">
            Below deductions NOT applicable under new regime — stored for reference only
          </div>
          <FR label="80C (LIC, PPF, ELSS, tuition fees…)"  path="deductions.sec_80c"    value={Number(ded.sec_80c || 0)}    conf={F("deductions.sec_80c")}    onEdit={E} indent />
          <FR label="80CCC (Pension fund)"                  path="deductions.sec_80ccc"  value={Number(ded.sec_80ccc || 0)}  onEdit={E} indent />
          <FR label="80CCD(1) (Employee NPS)"               path="deductions.sec_80ccd_1" value={Number(ded.sec_80ccd_1 || 0)} onEdit={E} indent />
          <FR label="80CCD(1B) (Additional NPS ₹50k)"      path="deductions.sec_80ccd_1b" value={Number(ded.sec_80ccd_1b || 0)} onEdit={E} indent />
          <FR label="80D (Health insurance)"                path="deductions.sec_80d"    value={Number(ded.sec_80d || 0)}    conf={F("deductions.sec_80d")}    onEdit={E} indent />
          <FR label="80E (Education loan interest)"         path="deductions.sec_80e"    value={Number(ded.sec_80e || 0)}    onEdit={E} indent />
          <FR label="80TTA (Savings interest, max ₹10,000)" path="deductions.sec_80tta"  value={Number(ded.sec_80tta || 0)}  onEdit={E} indent />
          <FR label="80TTB (Senior citizen FD interest)"    path="deductions.sec_80ttb"  value={Number(ded.sec_80ttb || 0)}  onEdit={E} indent />
          <FR label="80U (Disability)"                      path="deductions.sec_80u"    value={Number(ded.sec_80u || 0)}    onEdit={E} indent />
        </SC>

        {/* ── TAXABLE INCOME ─────────────────────────────────────────────── */}
        <div className="glass-card mb-4 px-6 py-4 flex justify-between items-center border border-purple-500/20">
          <span className="font-bold text-slate-200 text-sm uppercase tracking-wider">Taxable Income (GTI − Deductions)</span>
          <span className="text-xl font-bold text-purple-300 tabular-nums">{rupee(Number(tc.taxable_income || 0))}</span>
        </div>

        {/* ── TAX COMPUTATION ────────────────────────────────────────────── */}
        <SC title="Part B-ATI — Tax Computation (New Regime)" emoji="🧮">
          <FR label="Tax on total income (at slab rates)"  path="tax_computation.tax_before_rebate"   value={Number(tc.tax_before_rebate || 0)}   onEdit={E} />
          <FR label="Less: Rebate u/s 87A"                 path="tax_computation.rebate_87a"          value={Number(tc.rebate_87a || 0)}          conf={F("tax_computation.rebate_87a")} onEdit={E} indent />
          {exp["tax_computation.rebate_87a"] && (
            <div className="text-xs text-green-400 bg-green-900/10 border border-green-500/20 rounded-lg px-3 py-2 mb-2 ml-5">
              ✓ {exp["tax_computation.rebate_87a"]}
            </div>
          )}
          <FR label="Tax after rebate"                     path="tax_computation.tax_after_rebate"    value={Number(tc.tax_after_rebate || 0)}    onEdit={E} />
          <FR label="Add: Surcharge"                       path="tax_computation.surcharge"           value={Number(tc.surcharge || 0)}           onEdit={E} indent />
          <FR label="Add: Health & Education Cess @ 4%"   path="tax_computation.health_education_cess" value={Number(tc.health_education_cess || 0)} onEdit={E} indent />
          <SubTotal label="Total Tax Liability"             value={Number(tc.total_tax_liability || 0)} />
        </SC>

        {/* ── SCHEDULE TDS1: TDS FROM EMPLOYER ──────────────────────────── */}
        {tds0 && (Number(tds0.tds_deducted) > 0 || tds0.employer_name) && (
          <SC title="Schedule TDS1 — TDS from Salary (Employer)" emoji="🏢">
            <FR label="Employer / Deductor name"       path="tds_details.0.employer_name"       value={String(tds0.employer_name || "")}       conf={F("tds_details.0.employer_name")}  onEdit={E} />
            <FR label="TAN of deductor"                path="tds_details.0.employer_tan"        value={String(tds0.employer_tan || "")}        conf={F("tds_details.0.employer_tan")}   onEdit={E} />
            <FR label="Income chargeable under salary" path="tds_details.0.income_chargeable"   value={Number(tds0.income_chargeable || 0)}    onEdit={E} />
            <FR label="TDS deducted"                   path="tds_details.0.tds_deducted"        value={Number(tds0.tds_deducted || 0)}         conf={F("tds_details.0.tds_deducted")}  onEdit={E} />
            <FR label="TDS claimed this year"          path="tds_details.0.tds_claimed"         value={Number(tds0.tds_claimed || 0)}          onEdit={E} />
          </SC>
        )}

        {/* ── TAXES PAID & VERIFICATION ──────────────────────────────────── */}
        <SC title="Taxes Paid and Verification" emoji="✅"
          total={{ label: "Total Taxes Paid", value: Number(tc.total_taxes_paid || tc.tds_deducted || 0) }}>
          <FR label="TDS — from salary (Schedule TDS1)"    path="tax_computation.tds_deducted"      value={Number(tc.tds_deducted || 0)}      conf={F("tds_details.0.tds_deducted")} onEdit={E} />
          <FR label="TDS — from bank/interest (TDS2)"      path="tax_computation.tds_from_bank"     value={Number(tc.tds_from_bank || 0)}     onEdit={E} />
          <FR label="Advance tax paid"                     path="tax_computation.advance_tax_paid"  value={Number(tc.advance_tax_paid || 0)}  onEdit={E} />
          <FR label="Self-assessment tax paid"             path="tax_computation.self_assessment_tax" value={Number(tc.self_assessment_tax || 0)} onEdit={E} />
          <div className="pt-2" />
          <FR label="Interest u/s 234A"                    path="tax_computation.interest_234a"     value={Number(tc.interest_234a || 0)}     onEdit={E} />
          <FR label="Interest u/s 234B"                    path="tax_computation.interest_234b"     value={Number(tc.interest_234b || 0)}     onEdit={E} />
          <FR label="Interest u/s 234C"                    path="tax_computation.interest_234c"     value={Number(tc.interest_234c || 0)}     onEdit={E} />
          <FR label="Fee u/s 234F (late filing)"           path="tax_computation.fee_234f"          value={Number(tc.fee_234f || 0)}          onEdit={E} />
        </SC>

        {/* ── FINAL RESULT ───────────────────────────────────────────────── */}
        <div className={`glass-card p-8 text-center flex flex-col items-center border-t-4 mb-6
          ${Number(tc.refund || 0) > 0 ? "border-t-green-500" : "border-t-amber-500"}`}>
          {Number(tc.refund || 0) > 0 ? (
            <>
              <div className="text-sm font-bold text-green-400 uppercase tracking-widest mb-2">Estimated Refund</div>
              <div className="text-5xl font-bold text-slate-100 tabular-nums">{rupee(Number(tc.refund || 0))}</div>
              <div className="text-sm mt-3 text-slate-400">Credited to registered bank account after ITR processing</div>
              {exp["tax_computation.refund"] && (
                <div className="mt-3 text-xs text-green-300 bg-green-900/10 border border-green-500/20 rounded-lg px-4 py-2 max-w-lg">
                  {exp["tax_computation.refund"]}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="text-sm font-bold text-amber-400 uppercase tracking-widest mb-2">Net Tax Payable</div>
              <div className="text-5xl font-bold text-slate-100 tabular-nums">{rupee(Number(tc.tax_payable || 0))}</div>
              <div className="text-sm mt-3 text-slate-400">Pay via Challan 280 before filing deadline</div>
              {exp["tax_computation.tax_payable"] && (
                <div className="mt-3 text-xs text-amber-300 bg-amber-900/10 border border-amber-500/20 rounded-lg px-4 py-2 max-w-lg">
                  {exp["tax_computation.tax_payable"]}
                </div>
              )}
            </>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex flex-col md:flex-row items-center justify-center gap-4 hide-on-print">
          <a href={`/chat?session=${sessionId}`}
            className="inline-flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-purple-600 to-indigo-600 rounded-full
              text-white font-bold text-base shadow-lg hover:shadow-purple-500/30 transition-all transform hover:-translate-y-0.5">
            🤖 <span>Ask Tax AI</span>
          </a>
          <button onClick={() => window.open(`${API}/api/pipeline/export/${sessionId}?format=excel`, "_blank")}
            className="inline-flex items-center gap-2 px-6 py-4 bg-green-700/60 hover:bg-green-600/80
              border border-green-500/30 rounded-full text-white font-bold text-sm transition-all transform hover:-translate-y-0.5">
            📊 Download Filled Excel
          </button>
          <button onClick={() => window.open(`${API}/api/pipeline/export/${sessionId}?format=pdf`, "_blank")}
            className="inline-flex items-center gap-2 px-6 py-4 bg-white/10 hover:bg-white/20
              border border-white/20 rounded-full text-white font-bold text-sm transition-all transform hover:-translate-y-0.5">
            📄 Download as PDF
          </button>
        </div>
      </div>

      {edit && (
        <EditModal {...edit} sessionId={sessionId} onClose={() => setEdit(null)} onSaved={load} />
      )}
    </div>
  );
}

export default function FormPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center text-slate-400 text-sm">
        Loading your form…
      </div>
    }>
      <FormPageInner />
    </Suspense>
  );
}
