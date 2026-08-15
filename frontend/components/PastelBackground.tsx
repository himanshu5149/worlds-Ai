"use client";

import { motion } from "framer-motion";

/**
 * Slow-moving pastel mesh gradient — the signature Prism background.
 * Four soft blobs (lavender, mint, peach, baby blue) drift on an off-white
 * cream base; in dark mode they glow dimly over deep slate/indigo.
 */
export default function PastelBackground() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-cream transition-colors duration-700 dark:bg-night"
    >
      <div className="mesh-layer">
        <motion.div
          className="mesh-blob left-[4%] top-[2%] h-[46rem] w-[46rem] bg-lavender-200/80 dark:bg-lavender-500/15"
          animate={{ x: [0, 60, -40, 20, 0], y: [0, -50, 30, -20, 0] }}
          transition={{ duration: 34, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="mesh-blob right-[8%] top-[10%] h-[38rem] w-[38rem] bg-mint-200/80 dark:bg-mint-400/10"
          animate={{ x: [0, -70, 30, 40, 0], y: [0, 40, -60, 10, 0] }}
          transition={{ duration: 42, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="mesh-blob bottom-[-12%] left-[22%] h-[40rem] w-[40rem] bg-peach-200/80 dark:bg-peach-400/10"
          animate={{ x: [0, 50, -30, -60, 0], y: [0, -30, 50, -10, 0] }}
          transition={{ duration: 38, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="mesh-blob bottom-[6%] right-[14%] h-[34rem] w-[34rem] bg-babyblue-200/90 dark:bg-babyblue-500/15"
          animate={{ x: [0, -40, 60, -20, 0], y: [0, 30, -40, 20, 0] }}
          transition={{ duration: 46, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>
      {/* faint grain-free vignette keeps text readable */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-cream/60 dark:to-night/60" />
    </div>
  );
}
