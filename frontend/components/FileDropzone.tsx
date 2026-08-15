"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Paperclip, X } from "lucide-react";
import { useRef, useState } from "react";

export interface PendingFile {
  localId: string;
  name: string;
  size: number;
  type: string;
  serverId?: string;
  status: "ready" | "uploading" | "rejected";
  reason?: string;
}

interface Props {
  files: PendingFile[];
  onFiles: (files: PendingFile[]) => void;
  disabled?: boolean;
}

const MAX_MB = 10;
const ALLOWED = [
  "text/plain",
  "text/markdown",
  "text/csv",
  "application/json",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png",
  "image/jpeg",
];

/**
 * Drag-and-drop zone with a dashed pastel border. Files are validated
 * client-side (size/MIME) and then uploaded to the backend, which applies the
 * authoritative validation. Extracted text is wrapped in <user_document> tags
 * server-side to prevent prompt injection.
 */
export default function FileDropzone({ files, onFiles, disabled }: Props) {
  const [dragging, setDragging] = useState(false);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || disabled) return;
    const next: PendingFile[] = [...files];
    for (const file of Array.from(fileList).slice(0, 5)) {
      const localId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      if (file.size > MAX_MB * 1024 * 1024) {
        next.push({ localId, name: file.name, size: file.size, type: file.type, status: "rejected", reason: `over ${MAX_MB} MB` });
        continue;
      }
      if (!ALLOWED.includes(file.type)) {
        next.push({ localId, name: file.name, size: file.size, type: file.type, status: "rejected", reason: "unsupported type" });
        continue;
      }
      const entry: PendingFile = { localId, name: file.name, size: file.size, type: file.type, status: "uploading" };
      next.push(entry);
      onFiles(next);
      try {
        const { uploadFile } = await import("../lib/api");
        const { file_id } = await uploadFile(file);
        onFiles(
          next.map((f) => (f.localId === localId ? { ...f, status: "ready", serverId: file_id } : f)),
        );
      } catch {
        onFiles(
          next.map((f) => (f.localId === localId ? { ...f, status: "rejected", reason: "upload failed" } : f)),
        );
      }
    }
  };

  return (
    <div className="relative flex items-center">
      <motion.button
        whileTap={{ scale: 0.9 }}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-label="Attach files"
        className="glass pill flex h-11 w-11 items-center justify-center text-ink-soft hover:text-ink disabled:opacity-40 dark:text-slate-300 dark:hover:text-white"
      >
        {open ? <X size={17} strokeWidth={2.2} /> : <Paperclip size={17} strokeWidth={2.2} />}
      </motion.button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 380, damping: 28 }}
            className="glass-strong absolute bottom-14 left-0 z-30 w-72 rounded-3xl p-4 shadow-soft-lg"
          >
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                void handleFiles(e.dataTransfer.files);
              }}
              onClick={() => inputRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
                dragging
                  ? "border-lavender-400 bg-lavender-100/60 dark:bg-lavender-500/10"
                  : "border-lavender-300/70 bg-white/40 dark:border-slate-600 dark:bg-white/5"
              }`}
            >
              <Paperclip size={18} className="mb-1.5 text-lavender-500" />
              <p className="text-[12px] font-medium text-ink dark:text-slate-200">
                Drop files here or click to browse
              </p>
              <p className="mt-0.5 text-[10.5px] text-ink-soft dark:text-slate-400">
                txt · md · csv · json · pdf · docx · png · jpg — max {MAX_MB} MB
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                className="hidden"
                accept={ALLOWED.join(",")}
                onChange={(e) => void handleFiles(e.target.files)}
              />
            </div>
            {files.some((f) => f.status === "rejected") && (
              <p className="mt-2 text-[10.5px] text-coral-500">
                Some files were rejected (size/type). Attachments are scanned as untrusted input.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
