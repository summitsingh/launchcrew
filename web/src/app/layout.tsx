import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'LaunchCrew | Review desk', description: 'Demo launch drafts with individual approval and receipts.' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
