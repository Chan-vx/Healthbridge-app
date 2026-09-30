import type { NextConfig } from "next";

// The browser only ever talks to this Next.js server; it forwards API calls to
// FastAPI. One public address is then enough (Docker, Codespaces, any host).
// Docker builds set BACKEND_URL=http://backend:8000; local dev uses localhost.
const backend = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/docs", destination: `${backend}/docs` },
      { source: "/openapi.json", destination: `${backend}/openapi.json` },
    ];
  },
};

export default nextConfig;
