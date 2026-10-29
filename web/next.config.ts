import type { NextConfig } from 'next';
const config: NextConfig = {
  output: 'standalone',
  async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.API_URL || 'http://127.0.0.1:8000'}/api/:path*` }]; },
  async headers() {
    return [
      {
        // Frame protection and referrer handling are set here at the Next layer.
        // HSTS and X-Content-Type-Options are observed at the Cloudflare edge
        // for documents, and the backend middleware sets its own API headers,
        // so neither is duplicated here.
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        ],
      },
      {
        // Documents revalidate on every load instead of sitting in a shared
        // cache. Hashed static assets keep their Next defaults.
        source: '/',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' }],
      },
    ];
  },
};
export default config;
