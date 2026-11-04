// Route adapters keep existing screens usable while later steps replace them.
export function viewForWorkspacePath(pathname: string) {
  if (pathname === '/launches/new') return 'Idea';
  if (pathname.startsWith('/launches/')) return 'Run';
  if (pathname === '/schedule') return 'Calendar';
  if (pathname === '/settings') return 'Memory';
  return 'Queue';
}

export function runForWorkspacePath(pathname: string): string {
  if (!pathname.startsWith('/launches/') || pathname === '/launches/new') return '';
  try { return decodeURIComponent(pathname.slice('/launches/'.length)); }
  catch { return ''; }
}

export function pathForWorkspaceView(view: string, runId: string): string | null {
  if (view === 'Idea') return '/launches/new';
  if (view === 'Queue') return '/';
  if (view === 'Calendar') return '/schedule';
  if (view === 'Run' || view === 'Receipt') return runId ? `/launches/${encodeURIComponent(runId)}` : '/';
  return null;
}

export const workspaceHeadings: Record<string, { title: string; description: string }> = {
  Queue: { title: 'Launches', description: 'Review your launches and open a draft to see its checks and receipt.' },
  Idea: { title: 'New launch', description: 'Confirm your facts, then draft with Muse Spark and check every claim.' },
  Run: { title: 'Review', description: 'Review the draft and the facts behind it before approving the exact version.' },
  Receipt: { title: 'Receipt', description: 'Follow the checks, revisions, and approval recorded for this launch.' },
  Calendar: { title: 'Schedule', description: 'Ready slots publish automatically at their scheduled time. Any edit cancels Ready.' },
  Memory: { title: 'Settings', description: 'Manage your workspace and open its advanced tools.' },
  Agents: { title: 'Agents', description: 'Give each agent a clear role and boundary.' },
  Replay: { title: 'Replay', description: 'Compare two recorded runs.' },
  Campaign: { title: 'Campaigns', description: 'Review and approve each launch individually.' },
};
