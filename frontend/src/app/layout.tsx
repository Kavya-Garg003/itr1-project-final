import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title:       "ITR-1 AI Auto-Fill — Tax Assistant",
  description: "Upload Form 16 and let AI file your ITR-1 Sahaj automatically using advanced Vision OCR.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-800 antialiased font-sans flex flex-col min-h-screen">
        <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 px-6 py-4 flex justify-between items-center shadow-sm hide-on-print">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-blue-500 flex items-center justify-center text-white font-bold text-lg shadow-inner">
               T
            </div>
            <a href="/upload" className="font-semibold text-lg tracking-tight text-slate-900 hover:text-indigo-600">ITR-1 RAG App</a>
          </div>
          <nav className="flex gap-6 text-sm font-medium">
            <a href="/upload" className="text-slate-500 hover:text-indigo-600 transition-colors">Start Filing</a>
            <a href="/chat" className="text-slate-500 hover:text-indigo-600 transition-colors">General AI Chat</a>
          </nav>
        </header>

        <main className="flex-1 w-full mx-auto">
            {children}
        </main>
      </body>
    </html>
  );
}
