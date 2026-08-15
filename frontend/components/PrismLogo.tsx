"use client";

/** The glowing Prism mark — a rounded gradient gem. */
export default function PrismLogo({ size = 36 }: { size?: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-2xl bg-prism-gradient shadow-glow"
      style={{ width: size, height: size }}
    >
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5Z"
          fill="white"
          fillOpacity="0.9"
        />
        <path
          d="M12 6.5 17 9.3v5.4L12 17.5 7 14.7V9.3L12 6.5Z"
          fill="#fff"
          fillOpacity="0.45"
        />
      </svg>
    </div>
  );
}
