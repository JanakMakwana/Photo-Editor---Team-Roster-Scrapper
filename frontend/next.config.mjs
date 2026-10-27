/** @type {import('next').NextConfig} */
const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@radix-ui/themes'],
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/healthz',
        destination: `${backendUrl}/healthz`,
      },
    ];
  },
};

export default nextConfig;
