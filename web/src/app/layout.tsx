import type { Metadata } from 'next';
import { Inter, Plus_Jakarta_Sans, JetBrains_Mono } from 'next/font/google';
import './globals.css';
const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });
const jakarta = Plus_Jakarta_Sans({ subsets: ['latin'], variable: '--font-jakarta', display: 'swap' });
const jetbrains = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains', display: 'swap' });
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
// preference wins, otherwise the OS setting, otherwise light.
const themeInit = `(function(){try{var t=localStorage.getItem('launchcrew-theme');if(t!=='dark'&&t!=='light'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();`;
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${jakarta.variable} ${jetbrains.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">{children}</body>
    </html>
  );
}
