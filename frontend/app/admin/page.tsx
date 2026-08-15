"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Database,
  Gauge,
  GitMerge,
  Layers,
  Loader2,
  Timer,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import PastelBackground from "../../components/PastelBackground";
import PrismLogo from "../../components/PrismLogo";
import ThemeToggle from "../../components/ThemeToggle";
import { adminAlerts, adminMetrics, adminModels, getToken } from "../../lib/api";
import type { AdminMetrics, AdminModel, Alert } from "../../lib/types";

const STATUS_STYLES: Record<string, string> = {
  ACTIVE: "bg-mint-300 shadow-[0_0_14px_rgba(74,222,128,0.8)]",
  DEGRADED: "bg-peach-300 shadow-[0_0_12px_rgba(251,146,60,0.7)] animate-pulse-soft",
  COOLING: "bg-babyblue-300 shadow-[0_0_12px_rgba(96,165,250,0.7)] animate-pulse-soft",
  DOWN: "bg-coral-400 shadow-[0_0_12px_rgba(244,63,94,0.7)] animate-pulse-soft",
  AUTH_REQUIRED: "bg-slate-400 shadow-[0_0_10px_rgba(148,163,184,0.6)]",
  PAID_REQUIRED: "bg-coral-400 shadow-[0_0_12px_rgba(244,63,94,0.7)]",
  UNKNOWN: "bg-slate-300 shadow-none",
};

const DEMO_MODELS: AdminModel[] = [
  { id: "openai/gpt-4o-mini", provider: "openai", tier: "primary", routing_weight: 1.0, context_window: 128000, status: "ACTIVE", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "anthropic/claude-sonnet-4", provider: "anthropic", tier: "primary", routing_weight: 1.0, context_window: 200000, status: "ACTIVE", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "gemini/gemini-2.5-flash", provider: "gemini", tier: "primary", routing_weight: 0.9, context_window: 1000000, status: "DEGRADED", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "mistral/mistral-small-latest", provider: "mistral", tier: "secondary", routing_weight: 0.7, context_window: 128000, status: "ACTIVE", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "cohere/command-a-03-2025", provider: "cohere", tier: "secondary", routing_weight: 0.7, context_window: 256000, status: "PAID_REQUIRED", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "deepseek/deepseek-chat", provider: "deepseek", tier: "secondary", routing_weight: 0.8, context_window: 64000, status: "ACTIVE", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "xai/grok-4", provider: "xai", tier: "secondary", routing_weight: 0.7, context_window: 131072, status: "ACTIVE", capabilities: {}, requires_verification: false, credentials_required: true, last_health_check_at: null },
  { id: "ollama/llama3.2", provider: "ollama", tier: "local", routing_weight: 0.6, context_window: 131072, status: "DOWN", capabilities: {}, requires_verification: false, credentials_required: false, last_health_check_at: null },
];

const DEMO_METRICS: AdminMetrics = {
  window_hours: 24,
  total_requests: 1842,
  success_rate: 97.6,
  cache_hit_rate: 21.4,
  latency_p95_ms: 4120,
  fused_answers: 87,
  models: DEMO_MODELS.map((m) => ({
    model_id: m.id,
    provider: m.provider,
    status: m.status,
    success_rate_24h: m.status === "ACTIVE" ? 99.1 : m.status === "DEGRADED" ? 88.3 : null,
    latency_p95_ms: m.status === "ACTIVE" ? 3500 + Math.random() * 1500 : null,
    invocations_24h: Math.floor(Math.random() * 900) + 40,
  })),
};

const DEMO_ALERTS: Alert[] = [
  { severity: "critical", model_id: "cohere/command-a-03-2025", message: "cohere/command-a-03-2025 quota exhausted / payment required." },
  { severity: "critical", model_id: "ollama/llama3.2", message: "ollama/llama3.2 is DOWN." },
  { severity: "warning", model_id: "gemini/gemini-2.5-flash", message: "gemini/gemini-2.5-flash is degraded." },
];

export default function AdminPage() {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [models, setModels] = useState<AdminModel[] | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [demo, setDemo] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken()) {
        // Dashboard renders in demo mode without a token — clearly labeled.
        if (!cancelled) {
          setMetrics(DEMO_METRICS);
          setModels(DEMO_MODELS);
          setAlerts(DEMO_ALERTS);
          setDemo(true);
          setLoading(false);
        }
        return;
      }
      try {
        const [m, mo, a] = await Promise.all([adminMetrics(), adminModels(), adminAlerts()]);
        if (!cancelled) {
          setMetrics(m);
          setModels(mo);
          setAlerts(a.alerts);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setMetrics(DEMO_METRICS);
          setModels(DEMO_MODELS);
          setAlerts(DEMO_ALERTS);
          setDemo(true);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="relative min-h-dvh overflow-hidden px-5 pb-16 pt-6">
      <PastelBackground />
      <div className="relative z-10 mx-auto max-w-6xl">
        <header className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <PrismLogo size={38} />
            <div>
              <h1 className="font-display text-xl font-extrabold">Prism dashboard</h1>
              <p className="text-[12px] text-ink-soft dark:text-slate-400">
                Model availability · quotas · routing — bento view
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {demo && (
              <span className="rounded-full bg-peach-200/70 px-3 py-1.5 text-[10.5px] font-semibold text-peach-500 dark:bg-peach-400/15 dark:text-peach-300">
                demo data — connect the API (sign in as admin)
              </span>
            )}
            <Link
              href="/chat"
              className="glass rounded-full px-4 py-2 text-[12px] font-medium text-ink-soft shadow-soft hover:text-ink dark:text-slate-300 dark:hover:text-white"
            >
              ← Chat
            </Link>
            <ThemeToggle />
          </div>
        </header>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-24 text-ink-soft dark:text-slate-400">
            <Loader2 size={17} className="animate-spin" /> Loading telemetry…
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard
              icon={<Zap size={16} />}
              label="Success rate (24h)"
              value={metrics?.success_rate != null ? `${metrics.success_rate}%` : "—"}
              tint="bg-mint-200/60 text-green-600 dark:bg-mint-400/15 dark:text-mint-300"
            />
            <MetricCard
              icon={<Timer size={16} />}
              label="Latency p95"
              value={metrics?.latency_p95_ms != null ? `${(metrics.latency_p95_ms / 1000).toFixed(1)}s` : "—"}
              tint="bg-babyblue-200/60 text-blue-600 dark:bg-babyblue-500/15 dark:text-blue-300"
            />
            <MetricCard
              icon={<Database size={16} />}
              label="Cache hit rate"
              value={metrics?.cache_hit_rate != null ? `${metrics.cache_hit_rate}%` : "—"}
              tint="bg-lavender-200/60 text-violet-600 dark:bg-lavender-500/15 dark:text-violet-300"
            />
            <MetricCard
              icon={<GitMerge size={16} />}
              label="Fused answers"
              value={String(metrics?.fused_answers ?? 0)}
              tint="bg-peach-200/60 text-orange-600 dark:bg-peach-400/15 dark:text-peach-300"
            />
            <MetricCard
              icon={<Gauge size={16} />}
              label="Requests (24h)"
              value={String(metrics?.total_requests ?? 0)}
              tint="bg-babyblue-200/60 text-blue-600 dark:bg-babyblue-500/15 dark:text-blue-300"
              className="col-span-2 lg:col-span-2"
            />

            {/* model availability bento card */}
            <div className="glass col-span-2 rounded-4xl p-6 shadow-soft lg:col-span-4">
              <div className="mb-4 flex items-center gap-2">
                <Layers size={15} className="text-lavender-500" />
                <h2 className="font-display text-[14px] font-bold">Model availability</h2>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <AnimatePresence>
                  {(models ?? []).map((m, i) => (
                    <motion.div
                      key={m.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.04 }}
                      className="rounded-3xl border border-white/60 bg-white/45 p-4 dark:border-white/10 dark:bg-white/5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="truncate font-display text-[12.5px] font-semibold text-ink dark:text-slate-100">
                          {m.id}
                        </span>
                        <span
                          className={`h-2.5 w-2.5 rounded-full ${STATUS_STYLES[m.status] ?? STATUS_STYLES.UNKNOWN}`}
                          title={m.status}
                        />
                      </div>
                      <div className="mt-1 text-[10.5px] text-ink-soft dark:text-slate-400">
                        {m.status}
                        {m.requires_verification && " · requires verification"}
                        {m.credentials_required && !demo && " · key required"}
                      </div>
                      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-700">
                        <div
                          className="h-full rounded-full bg-send-gradient"
                          style={{ width: `${Math.min(100, Math.max(4, m.routing_weight * 45))}%` }}
                        />
                      </div>
                      <div className="mt-1 text-[10px] text-ink-soft/80 dark:text-slate-500">
                        routing weight {m.routing_weight.toFixed(2)}
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </div>

            {/* alerts bento card */}
            <div className="glass col-span-2 rounded-4xl p-6 shadow-soft lg:col-span-4">
              <div className="mb-4 flex items-center gap-2">
                <AlertTriangle size={15} className="text-coral-400" />
                <h2 className="font-display text-[14px] font-bold">Alerts</h2>
              </div>
              {alerts.length === 0 ? (
                <p className="text-[12.5px] text-mint-500">All clear — every monitored model is healthy.</p>
              ) : (
                <div className="space-y-2">
                  {alerts.map((a, i) => (
                    <div
                      key={i}
                      className={`flex items-center gap-2.5 rounded-2xl px-4 py-2.5 text-[12.5px] ${
                        a.severity === "critical"
                          ? "bg-coral-400/10 text-coral-500"
                          : a.severity === "warning"
                            ? "bg-peach-200/50 text-peach-500 dark:bg-peach-400/10 dark:text-peach-300"
                            : "bg-babyblue-200/50 text-blue-600 dark:bg-babyblue-500/15 dark:text-blue-300"
                      }`}
                    >
                      <span className={`h-2 w-2 shrink-0 rounded-full ${a.severity === "critical" ? "bg-coral-400" : "bg-peach-400"}`} />
                      {a.message}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function MetricCard({
  icon,
  label,
  value,
  tint,
  className = "",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tint: string;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className={`glass rounded-4xl p-6 shadow-soft ${className}`}
    >
      <div className={`mb-3 flex h-9 w-9 items-center justify-center rounded-2xl ${tint}`}>{icon}</div>
      <div className="font-display text-2xl font-extrabold">{value}</div>
      <div className="mt-0.5 text-[11.5px] text-ink-soft dark:text-slate-400">{label}</div>
    </motion.div>
  );
}
