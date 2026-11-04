import { DemoProviders } from '@/components/demo/demo-shell';

export default function JudgesLayout({ children }: { children: React.ReactNode }) {
  return <DemoProviders>{children}</DemoProviders>;
}
