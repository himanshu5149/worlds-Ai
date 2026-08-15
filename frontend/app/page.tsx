"use client";

import { motion } from "framer-motion";
import { ArrowRight, GitCompare, Layers, ShieldCheck, Sparkles, Timer } from "lucide-react";
import Link from "next/link";

import PastelBackground from "../components/PastelBackground";
import PrismLogo from "../components/PrismLogo";
import ThemeToggle from "../components/ThemeToggle";

const FEATURES = [
  {
    icon: Layers,
    title: "Parallel fan-out",
    body: "One question is routed to up to four eligible models at once, with per-model timeouts and typed failure handling.",
    tint: "bg-lavender-200/60 text-violet-600 dark:bg-lavender-500/15 dark:text-violet-300",
  },
  {
    icon: GitCompare,
    title: "Hybrid judging",
    body: "Answers are scored on relevance, factuality, completeness, readability and latency; top answers may be safely fused.",
    tint: "bg-mint-200/60 text-green-600 dark:bg-mint-400/15 dark:text-mint-300",
  },
  {
    icon: ShieldCheck,
    title: "Identity hidden",
    body: "The final answer says “Prism”. Candidates are anonymized; admin reveals are audited. Errors never leak provider internals.",
    tint: "bg-peach-200/60 text-orange-600 dark:bg-peach-400/15 dark:text-peach-300",
  },
  {
    icon: Timer,
    title: "Graceful degradation",
    body: "Cloud → user keys → local Ollama → safe semantic cache → queue → honest failure. Never a fabricated answer.",
    tint: "bg-babyblue-200/60 text-blue-600 dark:bg-babyblue-500/15 dark:text-blue-300",
  },
];

export default function LandingPage() {
  return (
    <main className="relative min-h-dvh overflow-hidden">
      <PastelBackground />
      <div className="absolute right-5 top-5 z-20">
        <ThemeToggle />
      </div>

      <div className="relative z-10 mx-auto flex max-w-5xl flex-col items-center px-6 pb-24 pt-20 text-center">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 220, damping: 24 }}
          className="flex flex-col items-center"
        >
          <PrismLogo size={64} />
          <h1 className="mt-7 max-w-3xl font-display text-5xl font-extrabold leading-[1.08] sm:text-6xl">
            One question. <span className="text-gradient">Many minds.</span>
            <br />
            One answer.
          </h1>
          <p className="mt-5 max-w-xl text-[15.5px] leading-relaxed text-ink-soft dark:text-slate-400">
            Prism fans your question out to multiple AI models in parallel, judges every answer,
            fuses the best when safe — and returns a single response under the Prism brand.
            The model that wrote it stays hidden by design.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/chat"
              className="flex items-center gap-2 rounded-full bg-send-gradient px-7 py-3.5 text-[14.5px] font-semibold text-white shadow-glow transition-transform hover:scale-[1.03] active:scale-95"
            >
              <Sparkles size={16} /> Start chatting <ArrowRight size={15} />
            </Link>
            <Link
              href="/admin"
              className="glass rounded-full px-7 py-3.5 text-[14.5px] font-semibold text-ink shadow-soft transition-transform hover:scale-[1.03] active:scale-95 dark:text-slate-100"
            >
              Open dashboard
            </Link>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, type: "spring", stiffness: 200, damping: 24 }}
          className="mt-16 grid w-full grid-cols-1 gap-4 sm:grid-cols-2"
        >
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="glass rounded-4xl p-6 text-left shadow-soft transition-transform hover:-translate-y-0.5"
            >
              <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-2xl ${f.tint}`}>
                <f.icon size={18} strokeWidth={2.2} />
              </div>
              <h3 className="font-display text-[15px] font-bold">{f.title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft dark:text-slate-400">
                {f.body}
              </p>
            </div>
          ))}
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.35 }}
          className="mt-16 max-w-lg text-[11.5px] leading-relaxed text-ink-soft/70 dark:text-slate-500"
        >
          Official APIs only. No scraping, no quota evasion, no invented endpoints. Your data can
          be deleted at any time, uploads are treated as untrusted input, and answers are never
          fabricated.
        </motion.p>
      </div>
    </main>
  );
}
