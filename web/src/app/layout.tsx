import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { NewUIProvider } from '@/components/new-ui-provider';
import './globals.css';
import './new-ui.css';

export const dynamic = 'force-dynamic';
const geist = Geist({ subsets: ['latin'], variable: '--font-geist-sans', display: 'swap' });
const geistMono = Geist_Mono({ subsets: ['latin'], variable: '--font-geist-mono', display: 'swap' });
export const metadata: Metadata = {
  metadataBase: new URL('https://launchcrew.summitsingh.com'),
  title: 'LaunchCrew: the trust layer for AI launch content',
  description: 'One idea in, a launch pack out: you confirm the facts, three agents draft, a strict Checker blocks anything unsupported, you approve the exact version, and it publishes with a receipt for every step. Try the live demo, no sign-up needed.',
  alternates: { canonical: '/' },
  icons: { icon: [{ url: '/favicon.ico', sizes: 'any' }, { url: '/favicon.svg', type: 'image/svg+xml' }] },
  openGraph: {
    title: 'LaunchCrew: the trust layer for AI launch content',
    description: 'One idea in, a launch pack out: you confirm the facts, three agents draft, a strict Checker blocks anything unsupported, you approve the exact version, and it publishes with a receipt for every step. Try the live demo, no sign-up needed.',
    url: 'https://launchcrew.summitsingh.com/',
    siteName: 'LaunchCrew',
    type: 'website',
    images: [
      {
        url: 'https://launchcrew.summitsingh.com/og-image.png',
        width: 1200,
        height: 630,
        alt: 'LaunchCrew: the trust layer for AI launch content',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'LaunchCrew: the trust layer for AI launch content',
    description: 'One idea in, a launch pack out: you confirm the facts, three agents draft, a strict Checker blocks anything unsupported, you approve the exact version, and it publishes with a receipt for every step. Try the live demo, no sign-up needed.',
    images: ['https://launchcrew.summitsingh.com/og-image.png'],
  },
};
// Runs before paint so the saved theme applies without a flash. Stored
// preference wins, otherwise light.
const themeInit = `(function(){try{var t=localStorage.getItem('launchcrew-theme');if(t!=='dark'&&t!=='light'){t='light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();`;
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const newUIEnabled = !['false', '0', 'off'].includes((process.env.LAUNCHCREW_NEW_UI ?? 'true').trim().toLowerCase());
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable} ${newUIEnabled ? 'new-ui-enabled' : ''}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased"><NewUIProvider enabled={newUIEnabled}>{children}</NewUIProvider></body>
    </html>
  );
}
