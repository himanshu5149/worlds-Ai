"use client";

import { motion } from "framer-motion";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { sendFeedback } from "../lib/api";

interface Props {
  requestId: string;
}

/**
 * Thumbs up/down — mint for up, soft coral for down. Feedback updates routing
 * weights via EMA server-side (no overreaction to single events).
 */
export default function FeedbackButtons({ requestId }: Props) {
  const [vote, setVote] = useState<1 | -1 | null>(null);

  const voteNow = async (rating: 1 | -1) => {
    if (vote !== null) return;
    setVote(rating);
    try {
      await sendFeedback(requestId, rating);
    } catch {
      /* keep optimistic state */
    }
  };

  return (
    <div className="flex gap-1.5">
      <motion.button
        whileTap={{ scale: 0.85 }}
        onClick={() => void voteNow(1)}
        aria-label="Good answer"
        className={`pill flex h-9 w-9 items-center justify-center transition-colors ${
          vote === 1
            ? "bg-mint-300 text-green-800 shadow-glow dark:bg-mint-400/30 dark:text-mint-200"
            : "glass text-ink-soft hover:text-green-600 dark:text-slate-400 dark:hover:text-mint-300"
        }`}
      >
        <ThumbsUp size={14} strokeWidth={2.2} />
      </motion.button>
      <motion.button
        whileTap={{ scale: 0.85 }}
        onClick={() => void voteNow(-1)}
        aria-label="Poor answer"
        className={`pill flex h-9 w-9 items-center justify-center transition-colors ${
          vote === -1
            ? "bg-coral-400/80 text-white shadow-glow"
            : "glass text-ink-soft hover:text-coral-500 dark:text-slate-400 dark:hover:text-coral-400"
        }`}
      >
        <ThumbsDown size={14} strokeWidth={2.2} />
      </motion.button>
    </div>
  );
}
