"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, deleteMyData, getDemoModeFlag, getToken, sendChat, setDemoModeFlag, setToken, streamChat, uploadFile } from "../lib/api";
import AuthCard from "./AuthCard";
import ChatInput from "./ChatInput";
import type { PendingFile } from "./FileDropzone";
import CompareModal from "./CompareModal";
import MessageBubble, { type BubbleMessage } from "./MessageBubble";
import PrismLogo from "./PrismLogo";

/** Demo answer used only when the backend is unreachable — clearly labeled. */
const DEMO_REPLY = `*Demo mode — the API is offline, so this reply is simulated locally.*\n\nOne question. Many minds. One answer. In a deployed Prism instance, your question would be fanned out to several eligible models in parallel, each answer scored for relevance, factuality, completeness, readability and latency — then the best (or a safe fusion of the top two) is returned here under the Prism brand, with model identities hidden.`;

export default function ChatInterface() {
  const [messages, setMessages] = useState<BubbleMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [authed, setAuthed] = useState<boolean>(() => Boolean(getToken()));
  const [sending, setSending] = useState(false);
  const [demoMode, setDemoMode] = useState<boolean>(
    () => typeof window !== "undefined" && !getToken() && getDemoModeFlag(),
  );
  const [compareRequest, setCompareRequest] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (text: string, files: PendingFile[]) => {
      if (sending) return;
      setSending(true);
      const userMsg: BubbleMessage = { id: `u-${Date.now()}`, role: "user", content: text };
      const pendingMsg: BubbleMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: "",
        pending: true,
      };
      setMessages((prev) => [...prev, userMsg, pendingMsg]);

      try {
        const attachments = files
          .filter((f) => f.status === "ready" && f.serverId)
          .map((f) => f.serverId as string);
        if (demoMode || !getToken()) {
          // Local simulation only when the backend is unreachable.
          await new Promise((r) => setTimeout(r, 900));
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingMsg.id
                ? { ...m, pending: false, content: DEMO_REPLY, requestId: `demo-${Date.now()}` }
                : m,
            ),
          );
        } else {
          const acc: string[] = [];
          try {
            for await (const chunk of streamChat(text, { conversationId, attachments })) {
              if (chunk.type === "token") {
                acc.push(chunk.text);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === pendingMsg.id
                      ? { ...m, pending: false, content: acc.join("") }
                      : m,
                  ),
                );
              } else if (chunk.type === "done") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === pendingMsg.id
                      ? { ...m, pending: false, content: acc.join(""), requestId: chunk.requestId || undefined }
                      : m,
                  ),
                );
              }
            }
          } catch (streamErr) {
            // Streaming failed -> fall back to the non-streaming endpoint.
            const resp = await sendChat(text, { conversationId, attachments });
            setMessages((prev) =>
              prev.map((m) =>
                m.id === pendingMsg.id
                  ? {
                      ...m,
                      pending: false,
                      content: resp.answer ?? resp.message ?? "No answer available.",
                      requestId: resp.request_id,
                      fromCache: resp.from_cache,
                      fused: resp.fused,
                    }
                  : m,
              ),
            );
          }
        }
      } catch (e) {
        const msg =
          e instanceof ApiError && e.status === 401
            ? "Your session expired — sign in again."
            : "Prism could not reach any eligible model right now. No answer was fabricated.";
        if (e instanceof ApiError && e.status === 401) setAuthed(false);
        setMessages((prev) =>
          prev.map((m) => (m.id === pendingMsg.id ? { ...m, pending: false, content: msg } : m)),
        );
        setDemoMode(true);
      } finally {
        setSending(false);
      }
    },
    [conversationId, demoMode, sending],
  );

  const regenerate = useCallback(
    (messageId: string) => {
      const idx = messages.findIndex((m) => m.id === messageId);
      if (idx < 0) return;
      const prevUser = [...messages.slice(0, idx)].reverse().find((m) => m.role === "user");
      if (!prevUser) return;
      setMessages((prev) => prev.slice(0, idx));
      void send(prevUser.content, []);
    },
    [messages, send],
  );

  const enterDemo = () => {
    setDemoModeFlag(true);
    setDemoMode(true);
  };

  const logout = () => {
    setToken(null);
    setDemoModeFlag(false);
    setAuthed(false);
    setDemoMode(false);
    setMessages([]);
    setConversationId(null);
  };

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <header className="mx-auto flex w-full max-w-3xl items-center justify-between px-5 pt-5">
        <div className="flex items-center gap-2.5">
          <PrismLogo size={32} />
          <span className="font-display text-[15px] font-bold">Prism</span>
          {demoMode && (
            <span
              className="rounded-full bg-peach-200/70 px-2.5 py-0.5 text-[10px] font-semibold text-peach-500 dark:bg-peach-400/15 dark:text-peach-300"
              title="Demo mode: no backend connected. Set PRISM_API_PROXY_URL to go live."
            >
              demo mode
            </span>
          )}
        </div>
        {authed ? (
          <button
            onClick={logout}
            className="glass flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[12px] font-medium text-ink-soft shadow-soft transition-colors hover:text-ink dark:text-slate-300 dark:hover:text-white"
          >
            <Settings2 size={13} /> Sign out
          </button>
        ) : null}
      </header>

      {/* messages */}
      <main ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-5 pb-4">
          {messages.length === 0 && (
            <div className="py-10 text-center">
              <motion.div
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: "spring", stiffness: 200, damping: 20 }}
                className="mx-auto mb-5 w-fit"
              >
                <PrismLogo size={58} />
              </motion.div>
              <h1 className="font-display text-2xl font-extrabold">
                One question. <span className="text-gradient">Many minds.</span> One answer.
              </h1>
              <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-relaxed text-ink-soft dark:text-slate-400">
                Prism fans your question out to several AI models in parallel, judges every answer,
                and returns a single response — without revealing which model wrote it.
              </p>
              {demoMode && (
                <p className="mx-auto mt-3 w-fit rounded-full bg-babyblue-200/50 px-4 py-1.5 text-[11px] font-medium text-blue-700 dark:bg-babyblue-500/15 dark:text-blue-200">
                  Demo mode — replies here are simulated. Connect the API to go live.
                </p>
              )}
            </div>
          )}
          {!authed && !demoMode && (
            <AuthCard onAuthed={() => setAuthed(true)} onDemo={enterDemo} />
          )}
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onRegenerate={authed ? regenerate : undefined}
                onCompare={authed ? setCompareRequest : undefined}
              />
            ))}
          </AnimatePresence>
        </div>
      </main>

      {/* composer */}
      <footer className="px-5 pb-5">
        <ChatInput onSend={(t, f) => void send(t, f)} disabled={sending} />
      </footer>

      <AnimatePresence>
        {compareRequest && (
          <CompareModal requestId={compareRequest} onClose={() => setCompareRequest(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}
