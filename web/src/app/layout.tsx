import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'LaunchCrew | Review desk',
  description: 'Demo launch drafts with individual approval and receipts. Demo facts only, nothing publishes.',
  icons: { icon: '/favicon.svg' },
  openGraph: {
    title: 'LaunchCrew review desk',
    description: 'Demo launch drafts with individual approval and receipts. Demo facts only, nothing publishes.',
    type: 'website',
  },
  twitter: {
    card: 'summary',
    title: 'LaunchCrew review desk',
    description: 'Demo launch drafts with individual approval and receipts. Demo facts only, nothing publishes.',
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
