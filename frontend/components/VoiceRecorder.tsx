"use client";

import { motion } from "framer-motion";
import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Props {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

/**
 * Voice input via MediaRecorder. The recorded blob is uploaded to the backend
 * (which transcribes via the configured Whisper/official API) when available;
 * otherwise a clearly-labeled local placeholder transcript is used.
 */
export default function VoiceRecorder({ onTranscript, disabled }: Props) {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const start = async () => {
    setError(null);
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Microphone unavailable in this browser.");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await transcribe(blob);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setError("Could not access the microphone.");
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
    setRecording(false);
  };

  const transcribe = async (blob: Blob) => {
    const { getToken } = await import("../lib/api");
    const token = getToken();
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    try {
      if (!token) throw new Error("not authenticated");
      const form = new FormData();
      form.append("file", blob, "voice.webm");
      const resp = await fetch(`${base}/api/v1/files/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const body = await resp.json().catch(() => ({}));
      if (resp.ok && body.extracted_chars) {
        onTranscript(String(body.extracted_text ?? ""));
        return;
      }
      throw new Error("transcription unavailable");
    } catch {
      // Transparent degradation: never pretend a real transcription exists.
      setError("Voice capture recorded, but transcription is unavailable (no speech backend configured).");
    }
  };

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return (
    <div className="relative flex items-center">
      {recording && (
        <motion.div
          initial={{ opacity: 0, x: 8 }}
          animate={{ opacity: 1, x: 0 }}
          className="mr-2 flex h-8 items-center gap-[3px] rounded-full bg-peach-200/50 px-3 dark:bg-peach-400/15"
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className="wave-bar"
              style={{ animationDelay: `${i * 0.13}s`, height: `${30 + (i % 3) * 20}%` }}
            />
          ))}
        </motion.div>
      )}
      <motion.button
        whileTap={{ scale: 0.9 }}
        onClick={recording ? stop : start}
        disabled={disabled}
        aria-label={recording ? "Stop recording" : "Record voice"}
        className={`pill flex h-11 w-11 items-center justify-center transition-colors disabled:opacity-40 ${
          recording
            ? "bg-coral-400 text-white shadow-glow"
            : "glass text-ink-soft hover:text-ink dark:text-slate-300 dark:hover:text-white"
        }`}
      >
        {recording ? <Square size={15} strokeWidth={2.4} /> : <Mic size={17} strokeWidth={2.2} />}
      </motion.button>
      {error && (
        <div className="glass-strong absolute bottom-14 left-0 z-20 w-64 rounded-2xl p-3 text-[11.5px] leading-relaxed text-ink-soft shadow-soft dark:text-slate-300">
          {error}
        </div>
      )}
    </div>
  );
}
