"use client";

import Link from "next/link";
import { LayoutDashboard } from "lucide-react";

import ChatInterface from "../../components/ChatInterface";
import PastelBackground from "../../components/PastelBackground";
import ThemeToggle from "../../components/ThemeToggle";

export default function ChatPage() {
  return (
    <div className="relative flex h-dvh flex-col">
      <PastelBackground />
      <div className="absolute right-4 top-4 z-20 flex items-center gap-2">
        <Link
          href="/admin"
          className="glass flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[12px] font-medium text-ink-soft shadow-soft transition-colors hover:text-ink dark:text-slate-300 dark:hover:text-white"
        >
          <LayoutDashboard size={13} /> Admin
        </Link>
        <ThemeToggle />
      </div>
      <ChatInterface />
    </div>
  );
}
