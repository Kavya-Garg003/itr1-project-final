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
  "What is the 80C deduction limit for AY 2024-25?",
  "Which tax regime is better for me?",
  "How is HRA exemption calculated?",
  "Can I file ITR-1 if I have FD income?",
  "What is the 87A rebate and who can claim it?",
  "What is the standard deduction for salaried employees?",
  "When is the last date to file ITR-1?",
  "What is Section 80D and what are the limits?",
];

// ── Citation card ──────────────────────────────────────────────────────────

function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-1">
      <div className="text-xs text-gray-400 font-medium mb-1.5">Sources</div>
      {citations.map((c, i) => (
        <a
          key={i}
          href={c.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-2 text-xs text-blue-600 hover:text-blue-800 group"
        >
          <span className="shrink-0 text-gray-300 group-hover:text-blue-400 mt-0.5">↗</span>
          <span>
            <span className="font-medium">{c.source}</span>
            {c.section && <span className="text-gray-400"> · {c.section}</span>}
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
      <div className="text-center text-xs text-gray-400 py-2">{msg.content}</div>
    );
  }

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium
        ${isUser ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600"}`}>
        {isUser ? "U" : "AI"}
      </div>

      {/* Bubble */}
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed
        ${isUser
          ? "bg-blue-600 text-white rounded-tr-sm"
          : "bg-white border border-gray-100 text-gray-800 rounded-tl-sm shadow-sm"}`}>

        {msg.loading ? (
          <div className="flex gap-1 items-center py-1">
            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
        ) : (
          <>
            {/* Render newlines */}
            <div className="whitespace-pre-wrap">{msg.content}</div>
            {!isUser && msg.citations && (
              <CitationList citations={msg.citations} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Regime mini-card (shown when form session active) ─────────────────────

function RegimeCard({ sessionId }: { sessionId: string }) {
  const [regime, setRegime] = useState<{
    recommended: string; old_tax: number; new_tax: number; saving: number
  } | null>(null);

  useEffect(() => {
    fetch(`${API}/api/pipeline/${sessionId}`)
      .then(r => r.json())
      .then(d => {
        const form = d?.itr1_form;
        if (!form) return;
        setRegime({
          recommended: form.regime_recommendation || "new",
          old_tax:     form.regime_tax_old || 0,
          new_tax:     form.regime_tax_new || 0,
          saving:      Math.abs((form.regime_tax_old || 0) - (form.regime_tax_new || 0)),
        });
      })
      .catch(() => {});
  }, [sessionId]);

  if (!regime) return null;

  return (
    <div className="mx-4 mb-3 border rounded-xl p-4 bg-green-50 border-green-200">
      <div className="text-xs font-medium text-green-800 mb-2">Your tax summary</div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-xs text-gray-500">Old regime</div>
          <div className="text-sm font-semibold text-gray-800">
            ₹{regime.old_tax.toLocaleString("en-IN")}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">New regime</div>
          <div className="text-sm font-semibold text-gray-800">
            ₹{regime.new_tax.toLocaleString("en-IN")}
          </div>
        </div>
        <div>
          <div className="text-xs text-green-700">Saving</div>
          <div className="text-sm font-semibold text-green-700">
            ₹{regime.saving.toLocaleString("en-IN")}
          </div>
        </div>
      </div>
      <div className="mt-2 text-xs text-green-800 text-center font-medium">
        ✓ {regime.recommended.toUpperCase()} regime recommended
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
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Nav */}
      <div className="bg-white border-b px-4 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          {sessionId && (
            <a href={`/form?session=${sessionId}`}
               className="text-sm text-gray-400 hover:text-gray-700">← Return</a>
          )}
          <div>
            <div className="font-medium text-gray-900 text-sm">Tax Assistant</div>
            <div className="text-xs text-gray-400">ITR-1 · AY 2024-25</div>
          </div>
        </div>
        <div className="text-xs text-gray-300">Answers grounded in official CBDT sources</div>
      </div>

      {/* Regime card (if session active) */}
      <div className="pt-3">
        {sessionId && <RegimeCard sessionId={sessionId} />}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 chat-scroll">
        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions (shown when only welcome message) */}
      {messages.length <= 1 && (
        <div className="px-4 pb-3">
          <div className="text-xs text-gray-400 mb-2 font-medium">Common questions</div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                onClick={() => send(s)}
                className="text-left text-xs border rounded-lg px-3 py-2.5 bg-white text-gray-600
                  hover:border-blue-300 hover:text-blue-700 transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="sticky bottom-0 bg-white border-t px-4 py-3">
        <div className="flex gap-2 items-end max-w-3xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about deductions, HRA, 87A rebate, regime choice…"
            rows={1}
            className="flex-1 resize-none border rounded-xl px-4 py-2.5 text-sm text-gray-800
              focus:outline-none focus:ring-2 focus:ring-blue-300 placeholder-gray-300
              min-h-[42px] max-h-[120px] overflow-y-auto"
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || loading}
            className="shrink-0 w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center
              hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4 rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <div className="text-center text-xs text-gray-300 mt-2">
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
