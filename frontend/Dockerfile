# ---- Prism AI frontend (Next.js standalone) ----
FROM node:20-alpine AS deps
WORKDIR /srv/prism
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /srv/prism
COPY --from=deps /srv/prism/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /srv/prism
ENV NODE_ENV=production
COPY --from=builder /srv/prism/.next/standalone ./
COPY --from=builder /srv/prism/.next/static ./.next/static
COPY --from=builder /srv/prism/public ./public 2>/dev/null || true
EXPOSE 3000
CMD ["node", "server.js"]
