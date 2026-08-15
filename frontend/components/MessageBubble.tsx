"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, Copy, GitCompare, RefreshCw } from "lucide-react";
import { useState } from "react";

import Markdown from "./Markdown";
import PrismLogo from "./PrismLogo";

export interface BubbleMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  requestId?: string;
  fromCache?: boolean;
  fused?: boolean;
}

interface Props {
  message: BubbleMessage;
  onRegenerate?: (messageId: string) => void;
  onCompare?: (requestId: string) => void;
}

/**
 * Chat bubbles per the design system:
 *  - user: soft peach → lavender gradient, aligned right, rounded-3xl
 *  - assistant: frosted glass (bg-white/70 backdrop-blur-md), aligned left,
 *    soft diffused shadow, "Prism" avatar with a soft glow
 *  - hover actions: pill-shaped Copy / Regenerate / Compare with spring motion
 */
export default function MessageBubble({ message, onRegenerate, onCompare }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const requestId = message.requestId;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
        className="flex justify-end"
      >
        <div className="max-w-[78%] rounded-3xl rounded-br-lg bg-gradient-to-br from-peach-100 via-peach-200/70 to-lavender-200/70 px-5 py-3.5 shadow-soft dark:from-night-soft dark:to-lavender-500/20">
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink dark:text-slate-100">
            {message.content}
          </p>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
      className="group flex items-start gap-3"
    >
      <div className="mt-0.5 shrink-0">
        <div className="rounded-2xl p-[2px] shadow-glow">
          <PrismLogo size={30} />
        </div>
      </div>
      <div className="w-full max-w-[82%]">
        <div className="mb-1.5 flex items-center gap-2 px-1">
          <span className="font-display text-[13px] font-semibold text-ink dark:text-slate-200">
            Prism
          </span>
          {message.fromCache && (
            <span className="rounded-full bg-babyblue-200/60 px-2 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-babyblue-500/20 dark:text-blue-200">
              cached
            </span>
          )}
          {message.fused && (
            <span className="rounded-full bg-lavender-200/60 px-2 py-0.5 text-[10px] font-medium text-violet-700 dark:bg-lavender-500/20 dark:text-violet-200">
              fused
            </span>
          )}
        </div>
        <div className="glass rounded-3xl rounded-tl-lg px-5 py-4 shadow-glass">
          {message.pending ? (
            <div className="flex items-center gap-2 py-1">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="h-2.5 w-2.5 rounded-full bg-lavender-400"
                  animate={{ opacity: [0.25, 1, 0.25], scale: [0.85, 1.1, 0.85] }}
                  transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }}
                />
              ))}
              <span className="ml-2 text-[13px] text-ink-soft dark:text-slate-400">
                Asking several models in parallel…
              </span>
            </div>
          ) : (
            <div className="text-[15px] leading-relaxed text-ink dark:text-slate-100">
              <Markdown text={message.content} />
            </div>
          )}
        </div>
        {/* hover actions */}
        {!message.pending && (
          <AnimatePresence>
            <motion.div
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 0, y: -6 }}
              whileHover={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 400, damping: 28 }}
              className="mt-1.5 flex gap-1.5 px-1"
            >
              <ActionPill onClick={copy} label={copied ? "Copied" : "Copy"}>
                {copied ? <Check size={13} /> : <Copy size={13} />}
              </ActionPill>
              {onRegenerate && (
                <ActionPill onClick={() => onRegenerate(message.id)} label="Regenerate">
                  <RefreshCw size={13} />
                </ActionPill>
              )}
              {requestId && onCompare && (
                <ActionPill onClick={() => onCompare(requestId)} label="Compare answers">
                  <GitCompare size={13} />
                </ActionPill>
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </motion.div>
  );
}

function ActionPill({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="glass flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11.5px] font-medium text-ink-soft shadow-soft transition-colors hover:text-ink dark:text-slate-300 dark:hover:text-white"
    >
      {children}
      {label}
    </button>
  );
}
