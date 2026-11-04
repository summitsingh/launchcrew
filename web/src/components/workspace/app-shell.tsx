'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { CalendarDays, ChevronsUpDown, Layers, LayoutList, LogOut, Plus, Search, Settings, UserRound, X } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/schema';
import { api, unwrap } from '@/lib/api';
import { launchStatus } from '@/lib/ui-status';
import { clearLastRunId } from '@/lib/last-run';
import { ThemeToggle, useThemePreference } from '@/components/theme-toggle';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command';
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger, useSidebar } from '@/components/ui/sidebar';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusLabel } from './status-label';

type Receipt = components['schemas']['Receipt'];
const destinations = [
  { href: '/', label: 'Launches', icon: LayoutList },
  { href: '/launches/new', label: 'New launch', icon: Plus },
  { href: '/schedule', label: 'Schedule', icon: CalendarDays },
  { href: '/settings', label: 'Settings', icon: Settings },
] as const;

function AccountMenu() {
  const client = useQueryClient();
  const { theme, changeTheme } = useThemePreference();
  const logout = useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSuccess: async () => {
      await client.cancelQueries();
      client.clear();
      clearLastRunId();
      window.location.assign('/');
    },
  });
  // The API has no dedicated first-name field. Use an avatar without reading
  // display, email, actor, or provider subject data into the chrome.
  return <>
    <DropdownMenu><DropdownMenuTrigger asChild><button type="button" className="workspace-account" aria-label="Open account menu"><Avatar><AvatarFallback><UserRound size={16} aria-hidden="true" /></AvatarFallback></Avatar><span>Your account</span><ChevronsUpDown size={16} aria-hidden="true" /></button></DropdownMenuTrigger>
      <DropdownMenuContent className="workspace-overlay w-56" side="top" align="start">
        <DropdownMenuCheckboxItem checked={theme === 'dark'} disabled={theme === null} onCheckedChange={checked => changeTheme(checked ? 'dark' : 'light')}>Dark mode</DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild><Link href="/settings"><Settings aria-hidden="true" />Settings</Link></DropdownMenuItem>
        <DropdownMenuItem disabled={logout.isPending} onSelect={event => { event.preventDefault(); logout.mutate(); }}><LogOut aria-hidden="true" />{logout.isPending ? 'Signing out...' : 'Sign out'}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {logout.isError && <p role="alert" className="workspace-error">Sign out failed. Open the menu and try again.</p>}
  </>;
}

function Navigation({ count, needsReview, authEnabled, signedIn, onSearch }: { count?: number; needsReview?: number; authEnabled: boolean; signedIn: boolean; onSearch: () => void }) {
  const pathname = usePathname();
  const { isMobile, setOpenMobile } = useSidebar();
  const close = () => setOpenMobile(false);
  return <Sidebar className="workspace-navigation">
    <SidebarHeader><div className="workspace-brand-row"><Link className="workspace-brand" href="/" onClick={close}><Layers size={21} aria-hidden="true" />LaunchCrew</Link>{isMobile && <button type="button" className="workspace-icon-button" aria-label="Close navigation" onClick={close}><X size={18} aria-hidden="true" /></button>}</div></SidebarHeader>
    <SidebarContent><ScrollArea className="min-h-0 flex-1"><nav aria-label="Workspace" className="workspace-nav"><SidebarMenu>
      {destinations.map(({ href, label, icon: Icon }) => <SidebarMenuItem key={href}><SidebarMenuButton asChild isActive={pathname === href || (href === '/' && pathname.startsWith('/launches/') && pathname !== '/launches/new')}><Link href={href} onClick={close} aria-current={pathname === href ? 'page' : undefined}><Icon aria-hidden="true" /><span>{label}</span>{href === '/' && count !== undefined && <span className="workspace-nav-count" aria-label={`${count} launches`}>{count}</span>}</Link></SidebarMenuButton></SidebarMenuItem>)}
      <SidebarMenuItem><SidebarMenuButton onClick={() => { close(); onSearch(); }}><Search aria-hidden="true" /><span>Search</span><span className="workspace-shortcut" aria-hidden="true">⌘ K</span></SidebarMenuButton></SidebarMenuItem>
    </SidebarMenu></nav>
    {needsReview !== undefined && <p className="workspace-review-count">Needs review <span>{needsReview}</span></p>}
    </ScrollArea></SidebarContent>
    <SidebarFooter>
      <p className="workspace-sidebar-note">Confirm facts. Review drafts. Approve and publish.</p>
      {!authEnabled && <div className="workspace-theme-row"><span>Appearance</span><ThemeToggle /></div>}
      {authEnabled && signedIn && <AccountMenu />}
    </SidebarFooter>
  </Sidebar>;
}

function WorkspaceCommand({ open, onOpenChange, launches, loading, failed, retry }: { open: boolean; onOpenChange: (open: boolean) => void; launches: Receipt[]; loading: boolean; failed: boolean; retry: () => void }) {
  const router = useRouter();
  const select = (href: string) => { onOpenChange(false); router.push(href); };
  return <CommandDialog open={open} onOpenChange={onOpenChange} title="Go to a launch or screen" description="Search screens and launch briefs. Use the arrow keys to choose a result and Enter to open it." className="workspace-overlay">
    <CommandInput placeholder="Search launches and screens..." aria-label="Search launches and screens" />
    <CommandList>
      <CommandEmpty>No matches. Try a product name or screen.</CommandEmpty>
      <CommandGroup heading="Screens">{destinations.map(({ href, label, icon: Icon }) => <CommandItem key={href} value={`screen ${label}`} onSelect={() => select(href)}><Icon aria-hidden="true" />{label}</CommandItem>)}<CommandItem value="Classic workspace" onSelect={() => select('/classic')}><Layers aria-hidden="true" />Classic workspace</CommandItem></CommandGroup>
      <CommandSeparator />
      <CommandGroup heading="Launches">
        {loading && <div className="p-3" role="status"><span className="sr-only">Loading launches</span><Skeleton className="h-8 w-full" /></div>}
        {failed && <p role="alert" className="px-3 py-2 text-sm">Launches could not load.</p>}
        {failed && <CommandItem value="Retry loading launches" onSelect={retry}>Try loading launches again</CommandItem>}
        {!loading && !failed && launches.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">No launches yet. Choose New launch to begin.</p>}
        {!failed && launches.map(receipt => <CommandItem key={receipt.run_id} value={`launch ${receipt.run_id} ${receipt.idea}`} onSelect={() => select(`/launches/${encodeURIComponent(receipt.run_id)}`)} className="items-start"><Layers aria-hidden="true" /><span className="min-w-0 flex-1 truncate">{receipt.idea || 'Untitled launch'}</span><StatusLabel status={launchStatus(receipt)} code={receipt.status} /></CommandItem>)}
      </CommandGroup>
    </CommandList>
  </CommandDialog>;
}

export function AppShell({ children, title, description, launches, queueLoading, queueFailed, retryQueue, authEnabled, signedIn }: { children: React.ReactNode; title: string; description: string; launches?: Receipt[]; queueLoading: boolean; queueFailed: boolean; retryQueue: () => void; authEnabled: boolean; signedIn: boolean }) {
  const [commandOpen, setCommandOpen] = useState(false);
  const needsReview = launches?.filter(receipt => launchStatus(receipt).label === 'Needs review').length;
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setCommandOpen(value => !value);
      }
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);
  return <div className="workspace-app" data-new-ui="true"><a className="workspace-skip" href="#workspace-content">Skip to content</a><SidebarProvider>
    <Navigation count={launches?.length} needsReview={needsReview} authEnabled={authEnabled} signedIn={signedIn} onSearch={() => setCommandOpen(true)} />
    <SidebarInset>
      <header className="workspace-topbar"><SidebarTrigger /><Breadcrumb><BreadcrumbList><BreadcrumbItem><BreadcrumbLink asChild><Link href="/">LaunchCrew</Link></BreadcrumbLink></BreadcrumbItem><BreadcrumbSeparator /><BreadcrumbItem><BreadcrumbPage>{title}</BreadcrumbPage></BreadcrumbItem></BreadcrumbList></Breadcrumb><button type="button" className="workspace-search-button" onClick={() => setCommandOpen(true)} aria-label="Search launches and screens"><Search size={16} aria-hidden="true" /><span>Search</span><span className="workspace-shortcut" aria-hidden="true">⌘ K</span></button></header>
      <div id="workspace-content" tabIndex={-1} className="workspace-content"><div className="workspace-heading"><h1>{title}</h1><p>{description}</p></div>{children}</div>
    </SidebarInset>
    <WorkspaceCommand open={commandOpen} onOpenChange={setCommandOpen} launches={launches ?? []} loading={queueLoading} failed={queueFailed} retry={retryQueue} />
  </SidebarProvider></div>;
}
