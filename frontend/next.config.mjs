/** @type {import('next').NextConfig} */
const rawBackend = (process.env.NEXT_PUBLIC_API_URL || '').trim() || 'http://127.0.0.1:8000';
const backendUrl = rawBackend.startsWith('http://') || rawBackend.startsWith('https://')
  ? rawBackend
  : `https://${rawBackend}`;

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
