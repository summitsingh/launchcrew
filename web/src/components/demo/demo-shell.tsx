'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  CalendarDays,
  LayoutGrid,
  PlusCircle,
  Settings as SettingsIcon,
} from 'lucide-react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { api, unwrap } from '@/lib/api';
import { CLASSIC_PATH, DEMO_UI_ENABLED } from '@/lib/demo-flag';
import { cn } from '@/lib/utils';

const queryClient = new QueryClient();

const NAV = [
  { href: '/meta-ai-hackathon-demo', label: 'Launches', icon: LayoutGrid },
  { href: '/meta-ai-hackathon-demo/launch', label: 'New launch', icon: PlusCircle },
  { href: '/meta-ai-hackathon-demo/schedule', label: 'Schedule', icon: CalendarDays },
  { href: '/meta-ai-hackathon-demo/settings', label: 'Settings', icon: SettingsIcon },
];

type AuthStatus = {
  enabled?: boolean;
  user?: string | null;
  display?: string | null;
  live_verified?: boolean;
};

/** Signed-out user menu: first name or avatar only, never the full name or provider id. */
export function DemoUserMenu() {
  const auth = useQuery({
    queryKey: ['demo-auth-status'],
    queryFn: () => unwrap(api.GET('/api/auth/status')),
    staleTime: 30000,
  });
  const data = (auth.data ?? {}) as AuthStatus;
  if (!data.enabled) {
    return (
      <span className="text-sm text-muted-foreground" data-testid="demo-user">
        Demo
      </span>
    );
  }
  if (!data.user) {
    return (
      <Link
        href={CLASSIC_PATH}
        className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        data-testid="demo-signin"
      >
        Owner sign-in
      </Link>
    );
  }
  const firstName = String(data.display ?? data.user).split(' ')[0] || 'Owner';
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="flex size-8 items-center justify-center rounded-full bg-primary text-sm font-medium text-primary-foreground"
          data-testid="demo-user"
          aria-label={`Signed in as ${firstName}`}
        >
          {firstName.charAt(0).toUpperCase()}
        </span>
      </TooltipTrigger>
      <TooltipContent>{firstName}</TooltipContent>
    </Tooltip>
  );
}

function DemoSidebar() {
  const pathname = usePathname();
  return (
    <Sidebar>
      <SidebarHeader>
        <Link href="/meta-ai-hackathon-demo" className="px-2 text-base font-semibold">
          LaunchCrew
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(item => {
                const active =
                  item.href === '/meta-ai-hackathon-demo'
                    ? pathname === item.href
                    : pathname.startsWith(item.href);
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton asChild isActive={active}>
                      <Link href={item.href}>
                        <item.icon aria-hidden />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <Link
          href={CLASSIC_PATH}
          className="px-2 text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          Classic workspace
        </Link>
      </SidebarFooter>
    </Sidebar>
  );
}

function DemoShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  return (
    <SidebarProvider open={sidebarOpen} onOpenChange={setSidebarOpen}>
      <DemoSidebar />
      <SidebarInset>
        <header className="flex h-12 items-center gap-2 border-b px-3">
          <SidebarTrigger data-testid="demo-sidebar-toggle" />
          <span className="text-sm font-medium">Meta AI hackathon demo</span>
          <span className={cn('ml-auto flex items-center gap-2')}>
            <DemoUserMenu />
          </span>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
      </SidebarInset>
      <Toaster />
    </SidebarProvider>
  );
}

/** Providers, sidebar shell, and flag gate for the judges workspace. */
export function DemoProviders({ children }: { children: React.ReactNode }) {
  if (!DEMO_UI_ENABLED) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <h1 className="text-xl font-semibold">Demo workspace is off</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The judges workspace is disabled in this build. Use the{' '}
          <Link href={CLASSIC_PATH} className="underline underline-offset-4">
            classic workspace
          </Link>{' '}
          instead.
        </p>
      </div>
    );
  }
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <DemoShell>{children}</DemoShell>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
