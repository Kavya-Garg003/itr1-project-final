import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title:       "ITR-1 AI Tax Assistant — Auto-Fill & Verify",
  description: "Upload Form 16. AI strictly applies 2025 New Tax Regime laws, fills your ITR-1 Sahaj, and lets you download the completed form.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body
        style={{ backgroundColor: "#0B1120", color: "#e2e8f0" }}
        className={`${inter.variable} font-sans antialiased flex flex-col min-h-screen`}
      >
        {/* ─── Global Header ──────────────────────────────────────── */}
        <header className="glass-header sticky top-0 z-50 px-6 py-3 flex justify-between items-center hide-on-print">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold text-xl shadow-lg shadow-blue-900/40">
              T
            </div>
            <div>
              <a href="/" className="font-bold text-base tracking-tight text-white hover:text-blue-300 transition-colors">
                ITR-1 Tax AI
              </a>
              <div className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold -mt-0.5">
                2025 New Regime · Strict Compliance
              </div>
            </div>
          </div>
          <nav className="flex gap-2 text-sm font-semibold">
            <a href="/"       className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-all">Home</a>
            <a href="/upload" className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-all">File ITR-1</a>
            <a href="/chat"   className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-all">Tax AI Chat</a>
          </nav>
        </header>

        <main className="flex-1 w-full mx-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
