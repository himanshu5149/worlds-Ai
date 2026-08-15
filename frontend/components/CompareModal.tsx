"use client";

import { AnimatePresence, motion } from "framer-motion";
import { GitCompare, Loader2, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, getCandidates } from "../lib/api";
import type { CandidatesResponse } from "../lib/types";
import Markdown from "./Markdown";

interface Props {
  requestId: string;
  onClose: () => void;
}

/**
 * "Compare Answers" — anonymized by default. Candidates are shown as
 * Candidate A/B/C with relative quality bars; model/provider names are
 * omitted unless the account is an admin (backend-enforced reveal).
 */
export default function CompareModal({ requestId, onClose }: Props) {
  const [data, setData] = useState<CandidatesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCandidates(requestId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Could not load candidates.");
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [requestId]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/25 p-4 backdrop-blur-sm dark:bg-black/50"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: 26, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 26, scale: 0.96 }}
        transition={{ type: "spring", stiffness: 300, damping: 28 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-strong max-h-[82vh] w-full max-w-2xl overflow-y-auto rounded-4xl p-6 shadow-soft-lg"
      >
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-lavender-200/60 text-violet-600 dark:bg-lavender-500/20 dark:text-violet-200">
              <GitCompare size={18} strokeWidth={2.2} />
            </div>
            <div>
              <h2 className="font-display text-lg font-bold">Compare answers</h2>
              <p className="text-[12px] text-ink-soft dark:text-slate-400">
                Candidates are anonymized by default — model names stay hidden.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close comparison"
            className="glass pill flex h-9 w-9 items-center justify-center text-ink-soft hover:text-ink dark:text-slate-300 dark:hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-12 text-ink-soft dark:text-slate-400">
            <Loader2 size={16} className="animate-spin" /> Loading candidates…
          </div>
        )}
        {error && (
          <div className="rounded-2xl bg-peach-100/70 p-4 text-[13px] text-peach-500 dark:bg-peach-400/10">
            {error}
          </div>
        )}

        <AnimatePresence>
          {data && (
            <div className="space-y-4">
              {data.candidates.map((c, i) => (
                <motion.div
                  key={c.label}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06, type: "spring", stiffness: 300, damping: 26 }}
                  className={`rounded-3xl border p-4 ${
                    c.is_winner
                      ? "border-lavender-300 bg-lavender-100/40 shadow-soft dark:border-lavender-500/30 dark:bg-lavender-500/10"
                      : "border-white/60 bg-white/40 dark:border-white/10 dark:bg-white/5"
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-display text-[13px] font-bold text-ink dark:text-slate-100">
                      {c.label}
                      {c.is_winner && (
                        <span className="ml-2 rounded-full bg-mint-200/70 px-2 py-0.5 text-[10px] font-semibold text-green-700 dark:bg-mint-400/20 dark:text-mint-300">
                          chosen answer
                        </span>
                      )}
                      {c.fused && (
                        <span className="ml-2 rounded-full bg-babyblue-200/70 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-babyblue-500/20 dark:text-blue-200">
                          fused
                        </span>
                      )}
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                        <div
                          className="h-full rounded-full bg-send-gradient"
                          style={{ width: `${Math.max(6, Math.min(100, c.score_pct))}%` }}
                        />
                      </div>
                      <span className="text-[10.5px] font-medium text-ink-soft dark:text-slate-400">
                        {c.score_pct}%
                      </span>
                    </div>
                  </div>
                  <div className="max-h-52 overflow-y-auto pr-1 text-[13.5px] leading-relaxed text-ink dark:text-slate-200">
                    <Markdown text={c.text} />
                  </div>
                  {data.revealed && c.model_id && (
                    <p className="mt-2 text-[10.5px] text-ink-soft dark:text-slate-500">
                      {c.model_id} (admin reveal)
                    </p>
                  )}
                </motion.div>
              ))}
              <p className="flex items-center justify-center gap-1.5 text-[10.5px] text-ink-soft/80 dark:text-slate-500">
                <ShieldCheck size={12} /> Identity hidden by design — admin reveal is audited.
              </p>
            </div>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  );
}
