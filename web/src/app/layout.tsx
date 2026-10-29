import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'LaunchCrew | Review desk',
  description: 'Launch drafts with individual approval and receipts. Product facts stay explicit, nothing publishes.',
  icons: { icon: '/favicon.svg' },
  openGraph: {
    title: 'LaunchCrew review desk',
    description: 'Launch drafts with individual approval and receipts. Product facts stay explicit, nothing publishes.',
    type: 'website',
  },
  twitter: {
    card: 'summary',
    title: 'LaunchCrew review desk',
    description: 'Launch drafts with individual approval and receipts. Product facts stay explicit, nothing publishes.',
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
