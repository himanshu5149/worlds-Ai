"use client";

import { motion } from "framer-motion";
import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";

import { ApiError, login, register, setToken } from "../lib/api";

/** Pastel glass auth card shown inline in the chat when no token exists. */
export default function AuthCard({
  onAuthed,
  onDemo,
}: {
  onAuthed: () => void;
  onDemo?: () => void;
}) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const resp = mode === "register" ? await register(email, password) : await login(email, password);
      setToken(resp.access_token);
      onAuthed();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 24 }}
      className="glass-strong mx-auto mt-8 w-full max-w-md rounded-4xl p-7 shadow-soft-lg"
    >
      <div className="mb-5 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-prism-gradient text-white shadow-glow">
          <Sparkles size={17} />
        </div>
        <div>
          <h2 className="font-display text-base font-bold">
            {mode === "register" ? "Create your account" : "Welcome back"}
          </h2>
          <p className="text-[12px] text-ink-soft dark:text-slate-400">
            One question → many models → one Prism answer.
          </p>
        </div>
      </div>
      <div className="space-y-3">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-2xl border border-white/70 bg-white/50 px-4 py-3 text-[14px] text-ink placeholder:text-ink-soft/60 focus:outline-none focus:ring-2 focus:ring-lavender-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
          placeholder="Password (min 8 characters)"
          className="w-full rounded-2xl border border-white/70 bg-white/50 px-4 py-3 text-[14px] text-ink placeholder:text-ink-soft/60 focus:outline-none focus:ring-2 focus:ring-lavender-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        />
        <button
          onClick={() => void submit()}
          disabled={busy || !email || password.length < 8}
          className="flex w-full items-center justify-center gap-2 rounded-full bg-send-gradient py-3 text-[14px] font-semibold text-white shadow-glow transition-opacity disabled:opacity-45"
        >
          {busy && <Loader2 size={15} className="animate-spin" />}
          {mode === "register" ? "Create account" : "Sign in"}
        </button>
        {error && (
          <p className="rounded-2xl bg-peach-100/70 px-3 py-2 text-[12px] text-coral-500 dark:bg-peach-400/10">
            {error}
          </p>
        )}
        <p className="pt-1 text-center text-[12px] text-ink-soft dark:text-slate-400">
          {mode === "register" ? "Already have an account?" : "New to Prism?"}{" "}
          <button
            className="font-semibold text-violet-600 hover:underline dark:text-violet-300"
            onClick={() => setMode(mode === "register" ? "login" : "register")}
          >
            {mode === "register" ? "Sign in" : "Create one"}
          </button>
        </p>
        {onDemo && (
          <button
            onClick={onDemo}
            className="w-full rounded-full border border-dashed border-lavender-300 py-2.5 text-[12px] font-semibold text-violet-600 transition-colors hover:bg-lavender-100/60 dark:border-lavender-500/40 dark:text-violet-300 dark:hover:bg-lavender-500/10"
          >
            Just exploring? Try demo mode (no backend needed)
          </button>
        )}
        <p className="text-center text-[10.5px] leading-relaxed text-ink-soft/70 dark:text-slate-500">
          Prism never shows which model answered. Candidates are anonymized unless you are an
          admin — and admin reveals are audited.
        </p>
      </div>
    </motion.div>
  );
}
