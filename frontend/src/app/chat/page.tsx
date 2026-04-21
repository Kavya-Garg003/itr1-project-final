"use client";

import { useState, useRef, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";

// ── Types ──────────────────────────────────────────────────────────────────

interface Citation {
  source:  string;
  url:     string;
  section: string;
}

type Role = "user" | "assistant" | "system";

interface Message {
  id:        string;
  role:      Role;
  content:   string;
  citations?: Citation[];
  loading?:  boolean;
}

// ── Suggested questions ─────────────────────────────────────────────────────

const SUGGESTIONS = [
  "What is the standard deduction for AY 2024-25 under the new regime?",
  "How is HRA exemption calculated?",
  "What is the 87A rebate and who can claim it?",
  "Is 80C applicable under the 2025 New Tax Regime?",
  "When is the last date to file ITR-1?",
  "Can I file ITR-1 if I have FD income?",
];

// ── Citation card ──────────────────────────────────────────────────────────

function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-4 pt-3 border-t border-white/10 space-y-2">
      <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Citations & Reasoning Sources</div>
      {citations.map((c, i) => (
        <a
          key={i}
          href={c.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-2 text-xs text-blue-400 hover:text-blue-300 group bg-white/5 p-2 rounded-lg border border-white/5 hover:border-blue-500/30 transition-all"
        >
          <span className="shrink-0 text-slate-500 group-hover:text-blue-400 mt-0.5">↗</span>
          <span>
            <span className="font-semibold">{c.source}</span>
            {c.section && <span className="text-slate-400 font-mono text-[10px] ml-1 block mt-0.5">SEC: {c.section}</span>}
          </span>
        </a>
      ))}
    </div>
  );
}

// ── Message bubble ─────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  if (msg.role === "system") {
    return (
      <div className="text-center text-xs text-slate-500 py-2 uppercase tracking-widest">{msg.content}</div>
    );
  }

  return (
    <div className={`flex gap-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shadow-lg
        ${isUser ? "bg-gradient-to-br from-blue-500 to-blue-700 text-white" : "bg-gradient-to-br from-purple-500 to-indigo-600 text-white"}`}>
        {isUser ? "U" : "AI"}
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] rounded-2xl px-5 py-4 text-sm leading-relaxed shadow-lg
        ${isUser
          ? "bg-blue-600 text-white rounded-tr-sm"
          : "glass-card text-slate-200 rounded-tl-sm border border-white/10"}`}>

        {msg.loading ? (
          <div className="flex gap-2 items-center py-2 h-6">
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
        ) : (
          <>
            {/* Render newlines */}
            <div className="whitespace-pre-wrap font-medium">{msg.content}</div>
            {!isUser && msg.citations && (
              <CitationList citations={msg.citations} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Main chat page ─────────────────────────────────────────────────────────

function ChatPageInner() {
  const params    = useSearchParams();
  const sessionId = params.get("session") || "";

  const [messages, setMessages] = useState<Message[]>([
    {
      id:      "welcome",
      role:    "assistant",
      content: sessionId
        ? "Hi! I can see your ITR-1 is filled. Ask me anything about your return, deductions, or tax rules for AY 2024-25."
        : "Hi! I'm your ITR-1 tax assistant for AY 2024-25. Ask me anything about filing your return, deductions, or tax rules.",
    },
  ]);
  const [input,   setInput]   = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef             = useRef<HTMLDivElement>(null);
  const inputRef              = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (!inputRef.current) return;
    inputRef.current.style.height = "auto";
    inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 120)}px`;
  }, [input]);

  const send = useCallback(async (question: string) => {
    if (!question.trim() || loading) return;

    const userMsg: Message = {
      id:      Date.now().toString(),
      role:    "user",
      content: question.trim(),
    };
    const loadingMsg: Message = {
      id:      "loading",
      role:    "assistant",
      content: "",
      loading: true,
    };

    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInput("");
    setLoading(true);

    try {
      const resp = await fetch(`${API}/api/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          question,
          session_id:           sessionId || undefined,
          ay:                   "AY2024-25",
          include_form_context: !!sessionId,
        }),
      });
      const data = await resp.json();

      const aiMsg: Message = {
        id:        Date.now().toString() + "_ai",
        role:      "assistant",
        content:   data.answer || "Sorry, I couldn't get an answer. Please try again.",
        citations: data.citations || [],
      };

      setMessages(prev => prev.filter(m => m.id !== "loading").concat(aiMsg));
    } catch {
      setMessages(prev =>
        prev.filter(m => m.id !== "loading").concat({
          id:      "err",
          role:    "assistant",
          content: "Network error. Make sure the backend is running.",
        })
      );
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [loading, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <div className="h-screen bg-[#0B1120] flex flex-col relative overflow-hidden">
      {/* Background */}
      <div className="absolute top-1/2 left-0 w-[500px] h-[500px] bg-purple-600/10 rounded-full blur-[100px] mix-blend-screen transform -translate-y-1/2 pointer-events-none" />

      {/* Nav */}
      <div className="glass-header px-6 py-4 flex items-center justify-between z-10">
        <div className="flex items-center gap-4">
          {sessionId && (
            <a href={`/form?session=${sessionId}`}
               className="text-sm text-blue-400 hover:text-blue-300 font-medium tracking-wide">← Return to Dashboard</a>
          )}
          <div>
            <div className="font-bold text-slate-100 text-lg">Contextual Tax AI</div>
            <div className="text-xs text-slate-400 tracking-wider">ITR-1 · 2025 NEW REGIME STRICT</div>
          </div>
        </div>
        <div className="text-xs text-green-400 font-mono tracking-widest bg-green-900/20 px-3 py-1 rounded-full border border-green-500/30 hidden md:block">
          ● VERIFIED RAG SOURCE CITATIONS ENGAGED
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 md:px-12 lg:px-32 py-8 space-y-6 chat-scroll z-10">
        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions (shown when only welcome message) */}
      {messages.length <= 1 && (
        <div className="px-4 md:px-12 lg:px-32 pb-6 z-10 fade-in-up">
          <div className="text-xs text-slate-500 mb-3 font-semibold uppercase tracking-widest">Common Inquiries</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                onClick={() => send(s)}
                className="text-left text-sm border border-white/10 rounded-xl px-4 py-3 glass-card text-slate-300
                  hover:border-blue-500/50 hover:bg-white/10 hover:text-blue-300 transition-all font-medium"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="glass-header px-4 md:px-12 lg:px-32 py-4 z-10 border-t border-white/10">
        <div className="flex gap-3 items-end max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about 2025 deductions, standard deduction, 87A rebate…"
            rows={1}
            className="flex-1 resize-none bg-slate-900/50 border border-slate-700 rounded-xl px-5 py-3 text-sm text-slate-100
              focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 placeholder-slate-500
              min-h-[46px] max-h-[120px] overflow-y-auto transition-colors"
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || loading}
            className="shrink-0 w-12 h-12 rounded-xl bg-blue-600 text-white flex items-center justify-center
              hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-[0_0_15px_rgba(37,99,235,0.3)]"
          >
            {loading ? (
              <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-5 h-5 translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <div className="text-center text-[10px] uppercase font-bold tracking-widest text-slate-500 mt-3">
          Enter to send · Shift+Enter for new line
        </div>
      </div>
    </div>
  );
}

// Next.js 14: useSearchParams must be inside a Suspense boundary
export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">
        Loading chat...
      </div>
    }>
      <ChatPageInner />
    </Suspense>
  );
}
