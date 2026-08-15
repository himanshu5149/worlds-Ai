import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Prism AI — one question, many minds, one answer",
  description:
    "Ask once. Prism fans your question out to multiple AI models in parallel, judges their answers, and returns a single high-quality response — without revealing which model produced it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Self-host in production; harmless fallback stacks otherwise. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap"
        />
        <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%23C084FC'/%3E%3Cstop offset='.5' stop-color='%23FB923C'/%3E%3Cstop offset='1' stop-color='%2360A5FA'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect x='4' y='4' width='24' height='24' rx='8' fill='url(%23g)'/%3E%3C/svg%3E" />
      </head>
      <body>{children}</body>
    </html>
  );
}
