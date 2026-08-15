"use client";

import React from "react";

/**
 * Minimal, XSS-safe markdown renderer: escape everything first, then apply a
 * few inline/block transforms on the escaped text. No dangerouslySetInnerHTML
 * with raw content, no external parser.
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInline(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, label, href) => {
    const safe = href.replace(/"/g, "%22");
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  return out;
}

export default function Markdown({ text }: { text: string }) {
  const html = React.useMemo(() => {
    const lines = text.split("\n");
    const out: string[] = [];
    let inCode = false;
    let codeBuf: string[] = [];
    let listBuf: string[] = [];
    let listType: "ul" | "ol" | null = null;

    const flushList = () => {
      if (listType && listBuf.length) {
        out.push(`<${listType}>${listBuf.map((l) => `<li>${l}</li>`).join("")}</${listType}>`);
      }
      listBuf = [];
      listType = null;
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("```")) {
        flushList();
        if (inCode) {
          out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
          codeBuf = [];
          inCode = false;
        } else {
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeBuf.push(line);
        continue;
      }
      const ul = trimmed.match(/^[-•*]\s+(.*)$/);
      const ol = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (ul) {
        if (listType !== "ul") {
          flushList();
          listType = "ul";
        }
        listBuf.push(renderInline(ul[1]));
        continue;
      }
      if (ol) {
        if (listType !== "ol") {
          flushList();
          listType = "ol";
        }
        listBuf.push(renderInline(ol[1]));
        continue;
      }
      flushList();
      if (!trimmed) continue;
      if (/^#{1,3}\s/.test(trimmed)) {
        const level = trimmed.match(/^(#{1,3})/)?.[1].length ?? 1;
        out.push(`<h${level}>${renderInline(trimmed.replace(/^#{1,3}\s/, ""))}</h${level}>`);
      } else {
        out.push(`<p>${renderInline(trimmed)}</p>`);
      }
    }
    flushList();
    if (inCode && codeBuf.length) {
      out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
    }
    return out.join("");
  }, [text]);

  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
