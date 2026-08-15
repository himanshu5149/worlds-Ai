"use client";

import { motion } from "framer-motion";
import { ArrowUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import FileDropzone, { type PendingFile } from "./FileDropzone";
import VoiceRecorder from "./VoiceRecorder";

interface Props {
  onSend: (text: string, attachments: PendingFile[]) => void;
  disabled?: boolean;
}

/**
 * The floating pill-shaped glassmorphic composer:
 * frosted glass, rounded-[2rem], soft pastel icon buttons, and a circular
 * gradient send button with a spring press animation.
 */
export default function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed, files);
    setText("");
    setFiles([]);
  };

  return (
    <div className="glass-strong mx-auto w-full max-w-3xl rounded-[2rem] p-2.5 shadow-soft-lg">
      <div className="flex items-end gap-2">
        <FileDropzone files={files} onFiles={setFiles} disabled={disabled} />
        <VoiceRecorder onTranscript={(t) => setText((prev) => (prev ? `${prev} ${t}` : t))} disabled={disabled} />
        <textarea
          ref={textareaRef}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Ask anything…"
          className="max-h-40 flex-1 resize-none bg-transparent px-2 py-2.5 font-body text-[15px] text-ink placeholder:text-ink-soft/60 focus:outline-none dark:text-slate-100 dark:placeholder:text-slate-500"
        />
        <motion.button
          onClick={submit}
          disabled={disabled || !text.trim()}
          whileTap={{ scale: 0.9 }}
          whileHover={{ scale: 1.06 }}
          aria-label="Send message"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-send-gradient text-white shadow-glow transition-opacity disabled:opacity-40"
        >
          <ArrowUp size={19} strokeWidth={2.4} />
        </motion.button>
      </div>
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pb-1 pt-1.5">
          {files.map((f) => (
            <span
              key={f.localId}
              className="flex items-center gap-1.5 rounded-full bg-lavender-200/50 px-3 py-1 text-[11px] font-medium text-violet-700 dark:bg-lavender-500/15 dark:text-violet-200"
            >
              📎 {f.name} ({Math.round(f.size / 1024)} KB)
              <button
                onClick={() => setFiles((prev) => prev.filter((x) => x.localId !== f.localId))}
                className="ml-0.5 opacity-60 hover:opacity-100"
                aria-label={`Remove ${f.name}`}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <p className="px-3 pb-1 pt-0.5 text-[10.5px] text-ink-soft/70 dark:text-slate-500">
        Prism fans your question out to several models and returns one answer. Model identity stays hidden.
      </p>
    </div>
  );
}
