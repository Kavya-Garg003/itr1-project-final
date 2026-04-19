/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",        // for Docker multi-stage build
  experimental: {
    serverActions: { allowedOrigins: ["localhost:3000"] },
  },
};

module.exports = nextConfig;
