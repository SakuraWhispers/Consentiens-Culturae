import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This app lives in a subdirectory of the Python monorepo; pin Turbopack's
  // root so stray package.json/package-lock.json files in parent directories
  // (e.g. the user profile) cannot leak into the build.
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
