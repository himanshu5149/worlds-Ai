/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // Production pattern: the browser calls /api/* same-origin and Vercel's edge
    // proxies to the hosted FastAPI backend. Set PRISM_API_PROXY_URL in the
    // Vercel project env (e.g. https://prism-api.up.railway.app). No CORS needed.
    // In local dev, NEXT_PUBLIC_API_URL (below) is used instead.
    const proxyUrl = process.env.PRISM_API_PROXY_URL?.replace(/\/$/, "");
    if (!proxyUrl) return [];
    return [{ source: "/api/:path*", destination: `${proxyUrl}/api/:path*` }];
  },
};

export default nextConfig;
