'use client';

import Link from 'next/link';
import { ChevronDown } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';

// Only the shell's Classic entry is introduced in Step 2. Settings panels
// continue to live in the preserved workspace until their work order step.
export function SettingsFoundation() {
  return <section aria-label="Workspace settings" className="workspace-settings">
    <Collapsible defaultOpen>
      <CollapsibleTrigger className="workspace-advanced-trigger">Advanced<ChevronDown size={16} aria-hidden="true" /></CollapsibleTrigger>
      <CollapsibleContent><div className="workspace-classic-link"><div><h2>Classic workspace</h2><p>Open the original workspace and its tools.</p></div><Button variant="outline" asChild><Link href="/classic">Open Classic workspace</Link></Button></div></CollapsibleContent>
    </Collapsible>
  </section>;
}
