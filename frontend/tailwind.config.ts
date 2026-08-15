import type { Config } from "tailwindcss";

/**
 * Prism AI — Pastel / Soft UI design tokens.
 * Mesh gradients: lavender #E9D5FF · mint #A7F3D0 · peach #FED7AA · baby blue #BFDBFE
 * Surfaces: off-white cream #FAFAF9 (light) · deep slate/indigo #0F172A (dark)
 */
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#FAFAF9",
        ink: "#1E1B2E",
        "ink-soft": "#6B6880",
        night: "#0F172A",
        "night-soft": "#1E293B",
        lavender: {
          50: "#F6F0FF",
          100: "#EFE4FF",
          200: "#E9D5FF",
          300: "#D8B4FE",
          400: "#C084FC",
          500: "#A855F7",
          600: "#9333EA",
        },
        mint: {
          50: "#F0FDF7",
          100: "#DCFCEA",
          200: "#BBF7D0",
          300: "#A7F3D0",
          400: "#4ADE80",
          500: "#22C55E",
        },
        peach: {
          50: "#FFF7F0",
          100: "#FFEDD5",
          200: "#FED7AA",
          300: "#FDBA74",
          400: "#FB923C",
        },
        babyblue: {
          50: "#F0F7FF",
          100: "#E1EFFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          400: "#60A5FA",
        },
        coral: {
          400: "#FB7185",
          500: "#F43F5E",
        },
      },
      fontFamily: {
        display: [
          '"Plus Jakarta Sans"',
          "Nunito",
          "Quicksand",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        body: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        "4xl": "2rem",
        blob: "42% 58% 63% 37% / 45% 45% 55% 55%",
      },
      boxShadow: {
        soft: "0 8px 32px rgba(168, 85, 247, 0.10), 0 2px 8px rgba(30, 27, 46, 0.06)",
        "soft-lg": "0 24px 64px -16px rgba(192, 132, 252, 0.25), 0 8px 24px rgba(30, 27, 46, 0.08)",
        glass: "0 8px 32px rgba(148, 163, 184, 0.18)",
        glow: "0 0 24px rgba(196, 181, 253, 0.55)",
      },
      backgroundImage: {
        "prism-gradient": "linear-gradient(135deg, #E9D5FF 0%, #A7F3D0 45%, #BFDBFE 100%)",
        "prism-gradient-soft": "linear-gradient(135deg, #F6F0FF 0%, #F0FDF7 50%, #F0F7FF 100%)",
        "send-gradient":
          "linear-gradient(135deg, #C084FC 0%, #FB923C 55%, #60A5FA 130%)",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translate(0, 0) scale(1)" },
          "33%": { transform: "translate(3rem, -2.5rem) scale(1.08)" },
          "66%": { transform: "translate(-2.5rem, 2rem) scale(0.94)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(0.96)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
      },
      animation: {
        float: "float 22s ease-in-out infinite",
        "float-slow": "float 30s ease-in-out infinite",
        "pulse-soft": "pulse-soft 2.2s ease-in-out infinite",
        shimmer: "shimmer 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
