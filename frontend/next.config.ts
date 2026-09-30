import type { NextConfig } from "next";

/**
 * The backend is a separate origin (`NEXT_PUBLIC_API_URL`). It already sends the
 * permissive CORS headers this app needs (verified against the live service), so
 * no rewrite proxy is used: data requests go straight to the API with a bearer
 * token, and only the session lifecycle passes through this server.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: false,
  poweredByHeader: false,
};

export default nextConfig;
