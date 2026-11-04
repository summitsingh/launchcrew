import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { NewUIProvider } from '@/components/new-ui-provider';
import './globals.css';
import './new-ui.css';

export const dynamic = 'force-dynamic';
const geist = Geist({ subsets: ['latin'], variable: '--font-geist-sans', display: 'swap' });
const geistMono = Geist_Mono({ subsets: ['latin'], variable: '--font-geist-mono', display: 'swap' });
export const metadata: Metadata = {
  title: 'LaunchCrew | Review desk',
  description: 'Launch drafts with individual approval and receipts. Product facts stay explicit; nothing publishes without passing the Ready gate.',
  icons: { icon: [{ url: '/favicon.ico', sizes: 'any' }, { url: '/favicon.svg', type: 'image/svg+xml' }] },
  openGraph: {
    title: 'LaunchCrew review desk',
    description: 'Launch drafts with individual approval and receipts. Product facts stay explicit; nothing publishes without passing the Ready gate.',
    type: 'website',
  },
  twitter: {
    card: 'summary',
    title: 'LaunchCrew review desk',
    description: 'Launch drafts with individual approval and receipts. Product facts stay explicit; nothing publishes without passing the Ready gate.',
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
