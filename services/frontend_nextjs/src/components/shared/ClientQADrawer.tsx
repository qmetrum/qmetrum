"use client";

import { useEffect, useRef, useState } from "react";
import { agentsApi } from "@/lib/api";
import { SourceDataPanel } from "@/components/shared/SourceDataPanel";
import { Markdown } from "@/components/shared/Markdown";
import { AGENT_DISCLAIMER, stripDisclaimer } from "@/components/shared/AgentCard";

type Metrics = Record<string, number | null | undefined>;

type Props = {
  open: boolean;
  onClose: () => void;
  portfolioId: number | string;
  portfolioName: string;
  metrics: Metrics;
  regime: string;
  snapshotHash?: string;
};

type Message =
  | { role: "user"; text: string }
  | {
      role: "agent";
      text: string;
      cached: boolean;
      sourceData: Record<string, unknown>;
    }
  | { role: "error"; text: string };

const SUGGESTED = [
  "What's this portfolio's biggest concentration risk?",
  "How would a 10% equity drop affect the biggest holding?",
  "Which of my active alerts matter most right now?",
];

export function ClientQADrawer({
  open,
  onClose,
  portfolioId,
  portfolioName,
  metrics,
  regime,
  snapshotHash,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      // Scroll to bottom when a new message appears
      const t = setTimeout(() => {
        scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
      }, 50);
      return () => clearTimeout(t);
    }
  }, [messages, open]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || pending) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setPending(true);
    try {
      const res = await agentsApi.clientQA(portfolioId, {
        question: q,
        metrics,
        regime,
        snapshot_hash: snapshotHash,
      });
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: res.answer, cached: res.cached, sourceData: res.source_data },
      ]);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        "Failed to answer";
      setMessages((prev) => [...prev, { role: "error", text: msg }]);
    } finally {
      setPending(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-white h-full flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--card-border)] px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Ask about {portfolioName}</h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Single-turn Q&A grounded in this portfolio&apos;s current data.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--navy)] text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-muted)]">Try one of these:</p>
              <div className="space-y-1.5">
                {SUGGESTED.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    className="block w-full text-left text-xs rounded-lg border border-[var(--card-border)] bg-[var(--content-bg)] hover:border-[var(--teal)] px-3 py-2 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => {
            if (m.role === "user") {
              return (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg bg-[var(--navy)] text-white px-3 py-2 text-sm">
                    {m.text}
                  </div>
                </div>
              );
            }
            if (m.role === "error") {
              return (
                <div key={i} className="text-xs text-[var(--coral)] px-2">
                  {m.text}
                </div>
              );
            }
            return (
              <div key={i} className="max-w-[90%]">
                <div className="rounded-lg bg-[var(--content-bg)] px-3 py-2 leading-relaxed">
                  <Markdown>{stripDisclaimer(m.text)}</Markdown>
                  {m.cached && (
                    <span className="mt-1 block text-[10px] text-[var(--text-muted)]">cached</span>
                  )}
                </div>
                <SourceDataPanel data={m.sourceData} />
              </div>
            );
          })}

          {pending && (
            <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              <span className="inline-block h-2 w-2 rounded-full bg-[var(--teal)] animate-pulse" />
              Thinking…
            </div>
          )}
        </div>

        <div className="border-t border-[var(--card-border)] p-3">
          <p className="mb-2 text-[10px] text-[var(--text-muted)]">{AGENT_DISCLAIMER}</p>
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              placeholder="Ask a question about this portfolio…"
              disabled={pending}
              className="flex-1 rounded-lg border border-[var(--card-border)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--teal)] disabled:opacity-50"
            />
            <button
              onClick={() => ask(input)}
              disabled={!input.trim() || pending}
              className="rounded-lg bg-[var(--teal)] text-white px-3 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
