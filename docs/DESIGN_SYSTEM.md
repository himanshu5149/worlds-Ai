# Pastel / Soft UI — design system reference

Source of truth: `frontend/tailwind.config.ts` + `frontend/app/globals.css`. Every Prism surface must follow these rules.

## Tokens

```ts
colors: {
  cream: "#FAFAF9",              // light background (never pure white)
  night: "#0F172A",              // dark background (deep slate/indigo, never pure black)
  lavender: { 200: "#E9D5FF", 400: "#C084FC", 500: "#A855F7" },
  mint:     { 200: "#BBF7D0", 300: "#A7F3D0" },
  peach:    { 200: "#FED7AA", 300: "#FDBA74" },
  babyblue: { 200: "#BFDBFE", 300: "#93C5FD" },
  coral:    { 400: "#FB7185" },   // destructive only (thumbs-down, errors)
}
fontFamily: {
  display: ['"Plus Jakarta Sans"', 'Nunito', 'Quicksand', ...sans],
  body: ['Inter', ...sans],
}
borderRadius: { "4xl": "2rem", blob: "42% 58% 63% 37% / 45% 45% 55% 55%" }
boxShadow: {
  soft:   "0 8px 32px rgba(168,85,247,.10), 0 2px 8px rgba(30,27,46,.06)",
  "soft-lg": "0 24px 64px -16px rgba(192,132,252,.25), …",
  glass:  "0 8px 32px rgba(148,163,184,.18)",
  glow:   "0 0 24px rgba(196,181,253,.55)",
}
```

## Component recipes

### Pastel mesh background
```tsx
<PastelBackground />
```
Four absolutely-positioned gradient blobs (`lavender-200/80`, `mint-200/80`, `peach-200/80`, `babyblue-200/90`), `filter: blur(90px)`, drifting on 34–46 s ease-in-out loops via Framer Motion. Dark mode: same hues at `/10–/15` opacity over `night`.

### Glassmorphism
```html
<!-- frosted glass card (light) -->
<div class="bg-white/60 backdrop-blur-md border border-white/60 rounded-3xl shadow-glass">
<!-- strong glass (modals / composer) -->
<div class="bg-white/75 backdrop-blur-xl border border-white/70 rounded-[2rem] shadow-soft-lg">
<!-- dark variants -->
<div class="dark:bg-slate-800/50 dark:border-white/10">
```

### Pill buttons
```html
<button class="rounded-full bg-send-gradient px-6 py-3 text-white shadow-glow
               hover:scale-[1.03] active:scale-95">…</button>
<button class="rounded-full bg-white/60 backdrop-blur-md border border-white/60 …">…</button>
```

### Chat bubbles
- User: `rounded-3xl rounded-br-lg bg-gradient-to-br from-peach-100 via-peach-200/70 to-lavender-200/70` right-aligned.
- Assistant: left-aligned glass bubble + `PrismLogo` avatar wrapped in `shadow-glow`; sender label is only ever "Prism"; optional chips `cached` (babyblue) and `fused` (lavender).
- Hover actions: `AnimatePresence` + `whileHover={{opacity:1, y:0}}` pill row (Copy · Regenerate · Compare answers) with `lucide-react` icons at `strokeWidth={2.2}` (soft stroke weight).

### Motion language
Spring physics only — no linear/ease-out pops:
```tsx
transition={{ type: "spring", stiffness: 300, damping: 28 }}
```
Micro-interactions: send button `whileTap={{scale:.9}}`, cards `hover:-translate-y-0.5`, typing indicator = three pulsing lavender dots (`opacity` + `scale` loops).

### Status dots (admin)
Glowing pastel dots: `ACTIVE` mint with `0 0 14px` glow · `DEGRADED` peach pulsing · `COOLING` babyblue pulsing · `DOWN`/`PAID_REQUIRED` coral pulsing · `AUTH_REQUIRED`/`UNKNOWN` muted slate.

### Icons
`lucide-react` exclusively, `strokeWidth={2.2}` (or 2.4 for emphasis) — soft, geometric strokes only. Never filled/duotone icon sets.

### Dark mode
`class` strategy, manual toggle (`ThemeToggle`), persisted to localStorage, respects `prefers-color-scheme` on first visit. Backgrounds switch to `night`/`night-soft`; glass layers darken to `slate-800/50`; pastel accents stay, at reduced saturation; shadows deepen slightly but never to black.

### Accessibility
Contrast: body text `ink (#1E1B2E)` on `cream` (≈ 12:1); muted text ≥ 4.5:1 on glass. All icon buttons carry `aria-label`s. Focus rings: `focus:ring-2 focus:ring-lavender-300`.
