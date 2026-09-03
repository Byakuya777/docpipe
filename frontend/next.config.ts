import type { NextConfig } from "next";

// The browser talks to the Next server only; /api/* is proxied through to
// FastAPI. Same-origin, so there is no CORS configuration anywhere.
// In Docker the backend is reachable as http://backend:8000; running
// `npm run dev` on the host falls back to localhost.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  experimental: {
    // Proxied request bodies are buffered in memory, capped at 10MB by
    // default. A batch of research papers blows straight past that, and an
    // oversized body is silently truncated rather than rejected — the backend
    // then drops the malformed multipart and the upload surfaces as a 500.
    // Batches are the whole point of this app, so raise it.
    proxyClientMaxBodySize: "100mb",
  },
};

export default nextConfig;
