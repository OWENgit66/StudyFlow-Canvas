import type { NextConfig } from "next";

const backend = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const nextConfig: NextConfig = {
  // Retain compatibility for explicit synchronous API clients. The UI uses 202 + polling.
  experimental: { proxyTimeout: 3_600_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
