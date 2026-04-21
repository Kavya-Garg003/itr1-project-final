import Link from "next/link";
import { ArrowRight, FileText, Bot, ShieldCheck, Zap } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6 relative overflow-hidden">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-600/20 rounded-full blur-3xl mix-blend-screen" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-600/20 rounded-full blur-3xl mix-blend-screen" />

      <div className="z-10 w-full max-w-5xl flex flex-col items-center text-center space-y-8 fade-in-up">
        {/* Badge */}
        <div className="glass-card px-4 py-2 rounded-full inline-flex items-center space-x-2 text-sm text-blue-300 border-blue-500/30">
          <Zap className="w-4 h-4 text-blue-400" />
          <span>Powered by Advanced Free Models</span>
        </div>

        {/* Hero Title */}
        <h1 className="text-5xl md:text-7xl font-bold tracking-tight pb-2">
          Automate Your <span className="text-gradient">Taxes.</span> <br />
          Verify with <span className="text-gradient">AI.</span>
        </h1>
        
        <p className="text-lg md:text-xl text-slate-300 max-w-2xl leading-relaxed delay-100 fade-in-up opacity-0" style={{ animationFillMode: "forwards" }}>
          Upload your Form 16 and Bank Statements. Our AI strictly enforces 2025 Tax Laws, fills your ITR-1, and answers all your financial questions with absolute transparency.
        </p>

        {/* CTA Cards */}
        <div className="grid md:grid-cols-2 gap-6 w-full max-w-4xl mt-12 delay-200 fade-in-up opacity-0" style={{ animationFillMode: "forwards" }}>
          
          {/* Dashboard/Upload Path */}
          <Link href="/upload" className="group">
            <div className="glass-card hover-glow rounded-2xl p-8 flex flex-col items-center text-center h-full transition-transform transform hover:-translate-y-2 cursor-pointer">
              <div className="w-16 h-16 rounded-full bg-blue-500/20 flex items-center justify-center mb-6 border border-blue-500/30 group-hover:bg-blue-500/40 transition-colors">
                <FileText className="w-8 h-8 text-blue-400" />
              </div>
              <h2 className="text-2xl font-semibold mb-3">Auto-Fill ITR-1</h2>
              <p className="text-slate-400 mb-6 text-sm">
                Securely drop your Form 16 and let AI instantly parse, structure, and compute your 2025 taxes.
              </p>
              <div className="mt-auto flex items-center text-blue-400 font-medium group-hover:text-blue-300">
                Go to Dashboard <ArrowRight className="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" />
              </div>
            </div>
          </Link>

          {/* RAG Chat Path */}
          <Link href="/chat" className="group">
            <div className="glass-card hover-glow rounded-2xl p-8 flex flex-col items-center text-center h-full transition-transform transform hover:-translate-y-2 cursor-pointer">
              <div className="w-16 h-16 rounded-full bg-purple-500/20 flex items-center justify-center mb-6 border border-purple-500/30 group-hover:bg-purple-500/40 transition-colors">
                <Bot className="w-8 h-8 text-purple-400" />
              </div>
              <h2 className="text-2xl font-semibold mb-3">Ask Tax AI</h2>
              <p className="text-slate-400 mb-6 text-sm">
                Chat with an expert AI about the 2025 New Tax Regime. Every answer includes citations and source reasoning.
              </p>
              <div className="mt-auto flex items-center text-purple-400 font-medium group-hover:text-purple-300">
                Start Chatting <ArrowRight className="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" />
              </div>
            </div>
          </Link>

        </div>

        {/* Feature row */}
        <div className="flex flex-wrap justify-center gap-6 mt-16 delay-300 fade-in-up opacity-0 text-slate-400 text-sm" style={{ animationFillMode: "forwards" }}>
          <div className="flex items-center"><ShieldCheck className="w-4 h-4 mr-2" /> Local Processing Available</div>
          <div className="flex items-center"><ShieldCheck className="w-4 h-4 mr-2" /> Anti-Hallucination Guardrails</div>
          <div className="flex items-center"><ShieldCheck className="w-4 h-4 mr-2" /> Strict 2025 Compliance</div>
        </div>
      </div>
    </main>
  );
}
