'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { CheckCircle2, MinusCircle } from 'lucide-react';
import { DemoButton, demoButtonVariants } from './demo-button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { api, unwrap } from '@/lib/api';
import { SUMMIT_LEATHER_FACTS, SUMMIT_LEATHER_IDEA, type StarterFact } from '@/lib/summit-leather-facts';

type WizardFact = StarterFact & { key: string };

let factCounter = 0;
function toWizardFacts(facts: StarterFact[]): WizardFact[] {
  return facts.map(fact => ({ ...fact, key: `fact-${++factCounter}` }));
}

const DEFAULT_FACTS = () => toWizardFacts(SUMMIT_LEATHER_FACTS);

type AgentProfile = { name?: string };

function agentNames(profiles: unknown): string[] {
  if (!Array.isArray(profiles)) return [];
  return (profiles as AgentProfile[])
    .map(profile => (typeof profile.name === 'string' ? profile.name : ''))
    .filter(Boolean);
}

function pickDefault(names: string[], preferred: string): string {
  if (names.includes(preferred)) return preferred;
  return names[0] ?? '';
}

type ProductFactSource = 'owner' | 'pasted_text' | 'memory' | 'listing' | 'campaign_brief' | 'demo_template' | 'drive_file';

type ProductFactField = { value: string; confirmed: boolean; source: ProductFactSource };

const VALID_SOURCES: ProductFactSource[] = [
  'owner',
  'pasted_text',
  'memory',
  'listing',
  'campaign_brief',
  'demo_template',
  'drive_file',
];

/** The API accepts only its source literal. The wizard records any source
 *  label the owner types, but only owner-confirmed facts become evidence,
 *  so anything outside the literal ships as owner-confirmed. */
function apiSource(source: string): ProductFactSource {
  const normalized = source.trim().toLowerCase();
  return (VALID_SOURCES as string[]).includes(normalized)
    ? (normalized as ProductFactSource)
    : 'owner';
}

function buildProductFacts(facts: WizardFact[]): {
  material?: ProductFactField;
  contents?: ProductFactField;
  size?: ProductFactField;
  price?: ProductFactField;
  allowed_claims: ProductFactField[];
} {
  const confirmed = facts.filter(fact => fact.confirmed && fact.claim.trim());
  const coreFor = (label: string): ProductFactField | undefined => {
    const match = confirmed.find(fact => fact.claim.toLowerCase().includes(label));
    if (!match) return undefined;
    return { value: match.claim.trim(), confirmed: true, source: apiSource(match.source) };
  };
  return {
    ...(coreFor('material') ? { material: coreFor('material') } : {}),
    allowed_claims: confirmed.map(fact => ({
      value: fact.claim.trim(),
      confirmed: true,
      source: apiSource(fact.source),
    })),
  };
}

export function NewLaunchWizard() {
  const [step, setStep] = useState(1);
  const [idea, setIdea] = useState(SUMMIT_LEATHER_IDEA);
  const [facts, setFacts] = useState<WizardFact[]>(DEFAULT_FACTS);
  const [scoutName, setScoutName] = useState('');
  const [makerName, setMakerName] = useState('');
  const [checkerName, setCheckerName] = useState('');
  const [agentsReady, setAgentsReady] = useState(false);
  const [checkerProfile, setCheckerProfile] = useState<'standard' | 'strict'>('standard');
  const [formatKind, setFormatKind] = useState('');
  const [trendPreset, setTrendPreset] = useState('');
  const [memoryText, setMemoryText] = useState('');
  const [waiveCore, setWaiveCore] = useState(false);
  const [runId, setRunId] = useState('');
  const [generateError, setGenerateError] = useState('');

  const agents = useQuery({
    queryKey: ['demo-agents'],
    queryFn: () => unwrap(api.GET('/api/agents')),
  });
  const formats = useQuery({
    queryKey: ['demo-formats'],
    queryFn: () => unwrap(api.GET('/api/formats')),
  });
  const presets = useQuery({
    queryKey: ['demo-trend-presets'],
    queryFn: () => unwrap(api.GET('/api/trends/presets')),
  });
  const templates = useQuery({
    queryKey: ['demo-quickstart-templates'],
    queryFn: () => unwrap(api.GET('/api/quickstart-templates')),
  });

  const names = useMemo(() => agentNames(agents.data), [agents]);
  useEffect(() => {
    if (names.length > 0 && !agentsReady) {
      setScoutName(pickDefault(names, 'Scout'));
      setMakerName(pickDefault(names, 'Maker'));
      setCheckerName(pickDefault(names, 'Checker'));
      setAgentsReady(true);
    }
  }, [names, agentsReady]);

  const formatOptions = useMemo(() => {
    const list = Array.isArray(formats.data) ? (formats.data as Record<string, unknown>[]) : [];
    return list.map(item => {
      const value = String(item.format_kind ?? item.id ?? item.name ?? '');
      const label = String(item.title ?? item.name ?? value);
      return { value, label };
    }).filter(option => option.value);
  }, [formats]);

  const trendOptions = useMemo(() => {
    const raw = presets.data as unknown;
    const list = Array.isArray(raw) ? raw : [];
    return (list as Record<string, unknown>[]).map(item => {
      const value = String(item.label ?? item.preset ?? item.id ?? '');
      return { value, label: value, source: String(item.source ?? '') };
    }).filter(option => option.value);
  }, [presets]);

  const templateOptions = useMemo(() => {
    const list = Array.isArray(templates.data) ? (templates.data as Record<string, unknown>[]) : [];
    return list.map(item => ({
      id: String(item.template_id ?? ''),
      title: String(item.title ?? item.template_id ?? ''),
    })).filter(option => option.id);
  }, [templates]);

  const loadExample = async (kind: 'summit' | string) => {
    if (kind === 'summit') {
      setFacts(toWizardFacts(SUMMIT_LEATHER_FACTS));
      setIdea(SUMMIT_LEATHER_IDEA);
      return;
    }
    const body = await unwrap(
      api.GET('/api/quickstart-templates/{template_id}', {
        params: { path: { template_id: kind } },
      }),
    );
    const record = body as unknown as Record<string, unknown>;
    if (typeof record.description === 'string' && record.description) setIdea(record.description);
    const claims = Array.isArray(record.approved_claims) ? record.approved_claims : [];
    const sources = Array.isArray(record.sources) ? record.sources : [];
    if (claims.length > 0) {
      setFacts(
        toWizardFacts(
          claims
            .filter((claim): claim is string => typeof claim === 'string' && !!claim.trim())
            .map((claim, index) => ({
              claim,
              source: typeof sources[index] === 'string' ? (sources[index] as string) : 'template',
              confirmed: true,
            })),
        ),
      );
    }
  };

  const confirmedCount = facts.filter(fact => fact.confirmed && fact.claim.trim()).length;

  const generate = useMutation({
    mutationFn: async () => {
      setGenerateError('');
      const productFacts = buildProductFacts(facts);
      const trend = trendOptions.find(option => option.value === trendPreset);
      const response = await unwrap(
        api.POST('/api/runs/async', {
          body: {
            idea: idea.trim(),
            agent_name: makerName || 'Maker',
            seed_unverified_claim: false,
            ...(scoutName ? { scout_name: scoutName } : {}),
            ...(makerName ? { maker_name: makerName } : {}),
            ...(checkerName ? { checker_name: checkerName } : {}),
            checker_profile: checkerProfile,
            ...(formatKind ? { format_spec: { format_kind: formatKind } } : {}),
            ...(trend && trend.source ? { trend_label: trend.value, trend_source: trend.source } : {}),
            memory_ids: memoryText.trim()
              ? memoryText.split(',').map(part => part.trim()).filter(Boolean)
              : [],
            product_facts: productFacts,
            waive_missing_core_facts: waiveCore,
          },
        }),
      );
      return response as unknown as { run_id: string };
    },
    onSuccess: created => setRunId(created.run_id),
    onError: (error: Error) => setGenerateError(error.message),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">New launch</h1>
        <p className="mt-1 text-sm text-muted-foreground">Step {step} of 3</p>
      </div>

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Describe the product</CardTitle>
            <CardDescription>One paragraph is enough. The agents draft from this.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              value={idea}
              onChange={event => setIdea(event.target.value)}
              rows={5}
              aria-label="Product description"
              data-testid="demo-idea"
            />
            <div className="flex justify-end">
              <DemoButton onClick={() => setStep(2)} disabled={!idea.trim()} data-testid="demo-step-next">
                Continue to facts
              </DemoButton>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Confirm facts</CardTitle>
            <CardDescription>
              Only confirmed facts become evidence. Unconfirmed rows are ignored.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <DemoButton variant="outline" data-testid="demo-example-menu">
                  Start from an example
                </DemoButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onSelect={() => void loadExample('summit')}>
                  Summit Leather Co.
                </DropdownMenuItem>
                {templateOptions.map(option => (
                  <DropdownMenuItem key={option.id} onSelect={() => void loadExample(option.id)}>
                    {option.title}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <ul className="space-y-3">
              {facts.map(fact => (
                <li key={fact.key} className="flex flex-wrap items-center gap-2 rounded-md border p-3">
                  <input
                    type="checkbox"
                    checked={fact.confirmed}
                    onChange={event =>
                      setFacts(prev =>
                        prev.map(item =>
                          item.key === fact.key ? { ...item, confirmed: event.target.checked } : item,
                        ),
                      )
                    }
                    aria-label={`Confirm fact ${fact.claim || 'empty'}`}
                    data-testid={`demo-fact-confirm-${fact.key}`}
                  />
                  <Input
                    value={fact.claim}
                    onChange={event =>
                      setFacts(prev =>
                        prev.map(item =>
                          item.key === fact.key ? { ...item, claim: event.target.value } : item,
                        ),
                      )
                    }
                    placeholder="Fact"
                    aria-label="Fact"
                    className="min-w-40 flex-1"
                  />
                  <Input
                    value={fact.source}
                    onChange={event =>
                      setFacts(prev =>
                        prev.map(item =>
                          item.key === fact.key ? { ...item, source: event.target.value } : item,
                        ),
                      )
                    }
                    placeholder="Source"
                    aria-label="Source"
                    className="w-40"
                  />
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <DemoButton
                variant="outline"
                onClick={() => setFacts(prev => [...prev, { key: `fact-${++factCounter}`, claim: '', source: '', confirmed: true }])}
              >
                Add fact
              </DemoButton>
              <span className="text-sm text-muted-foreground">
                {confirmedCount} confirmed
              </span>
            </div>
            <Collapsible>
              <CollapsibleTrigger asChild>
                <DemoButton variant="ghost" data-testid="demo-options-toggle">
                  Options
                </DemoButton>
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-4 pt-2">
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="space-y-1">
                    <Label htmlFor="demo-scout">Scout</Label>
                    <Select value={scoutName} onValueChange={setScoutName}>
                      <SelectTrigger id="demo-scout">
                        <SelectValue placeholder="Scout" />
                      </SelectTrigger>
                      <SelectContent>
                        {names.map(name => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-maker">Maker</Label>
                    <Select value={makerName} onValueChange={setMakerName}>
                      <SelectTrigger id="demo-maker">
                        <SelectValue placeholder="Maker" />
                      </SelectTrigger>
                      <SelectContent>
                        {names.map(name => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-checker">Checker</Label>
                    <Select value={checkerName} onValueChange={setCheckerName}>
                      <SelectTrigger id="demo-checker">
                        <SelectValue placeholder="Checker" />
                      </SelectTrigger>
                      <SelectContent>
                        {names.map(name => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="space-y-1">
                    <Label htmlFor="demo-checker-profile">Checker profile</Label>
                    <Select
                      value={checkerProfile}
                      onValueChange={value => setCheckerProfile(value === 'strict' ? 'strict' : 'standard')}
                    >
                      <SelectTrigger id="demo-checker-profile">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="standard">Standard</SelectItem>
                        <SelectItem value="strict">Strict</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-format">Format</Label>
                    <Select value={formatKind} onValueChange={setFormatKind}>
                      <SelectTrigger id="demo-format">
                        <SelectValue placeholder="No format" />
                      </SelectTrigger>
                      <SelectContent>
                        {formatOptions.map(option => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-trend">Trend format</Label>
                    <Select value={trendPreset} onValueChange={setTrendPreset}>
                      <SelectTrigger id="demo-trend">
                        <SelectValue placeholder="No trend" />
                      </SelectTrigger>
                      <SelectContent>
                        {trendOptions.map(option => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="demo-memory">Memory (comma ids)</Label>
                    <Input
                      id="demo-memory"
                      value={memoryText}
                      onChange={event => setMemoryText(event.target.value)}
                      placeholder="mem_1, mem_2"
                    />
                  </div>
                  <div className="flex items-center gap-2 pt-5">
                    <input
                      type="checkbox"
                      id="demo-waive-core"
                      checked={waiveCore}
                      onChange={event => setWaiveCore(event.target.checked)}
                    />
                    <Label htmlFor="demo-waive-core">
                      Proceed without all core facts (recorded on the receipt)
                    </Label>
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>
            <div className="flex justify-between">
              <DemoButton variant="outline" onClick={() => setStep(1)}>
                Back
              </DemoButton>
              <DemoButton onClick={() => setStep(3)} data-testid="demo-step-next">
                Continue to generate
              </DemoButton>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>Generate</CardTitle>
            <CardDescription>One run. The draft and the receipt are the focus.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">{idea}</p>
            <p className="text-sm text-muted-foreground">
              {confirmedCount} confirmed facts. Scout {scoutName || 'default'}, Maker{' '}
              {makerName || 'default'}, Checker {checkerName || 'default'} ({checkerProfile}
              ).
            </p>
            {runId ? (
              <RunTracker runId={runId} />
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <DemoButton variant="outline" onClick={() => setStep(2)}>
                  Back
                </DemoButton>
                <DemoButton
                  onClick={() => generate.mutate()}
                  disabled={generate.isPending || !idea.trim()}
                  data-testid="demo-generate"
                >
                  {generate.isPending ? 'Starting…' : 'Generate launch'}
                </DemoButton>
              </div>
            )}
            {generateError && (
              <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                {generateError}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function RunTracker({ runId }: { runId: string }) {
  const receipt = useQuery({
    queryKey: ['demo-receipt', runId],
    queryFn: () => unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: runId } } })),
    refetchInterval: query => {
      const data = query.state.data as unknown as { status?: string } | undefined;
      return data && (data.status === 'completed' || data.status === 'failed') ? false : 2500;
    },
  });
  const steps = useQuery({
    queryKey: ['demo-steps', runId],
    queryFn: () =>
      unwrap(api.GET('/api/runs/{run_id}/steps', { params: { path: { run_id: runId } } })),
    refetchInterval: 2000,
  });
  const data = receipt.data as unknown as { status?: string } | undefined;
  const terminal = data?.status === 'completed' || data?.status === 'failed';
  const list = Array.isArray((steps.data as unknown as { steps?: unknown })?.steps)
    ? ((steps.data as unknown as { steps: { stage: string; state: string; profile?: string }[] }).steps)
    : [];

  return (
    <div className="space-y-3" data-testid="demo-run-tracker">
      {steps.isPending && <Skeleton className="h-8 w-full" />}
      <ol className="space-y-1 text-sm">
        {list.map(item => (
          <li key={item.stage} className="flex items-center gap-2">
            {item.state === 'completed' ? (
              <CheckCircle2 className="size-4 text-green-700 dark:text-green-300" aria-hidden />
            ) : (
              <MinusCircle className="size-4 text-muted-foreground" aria-hidden />
            )}
            <span>{item.stage}</span>
            <span className="text-muted-foreground">
              {item.state}, {/spark/i.test(item.profile ?? '') ? 'Muse Spark' : 'Deterministic'}
            </span>
          </li>
        ))}
      </ol>
      {terminal && data?.status === 'completed' && (
        <Link
          href={`/meta-ai-hackathon-demo/review/${runId}`}
          data-testid="demo-open-review"
          className={demoButtonVariants()}
        >
          Open review
        </Link>
      )}
      {terminal && data?.status === 'failed' && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          The run failed. The receipt records why.
        </p>
      )}
    </div>
  );
}
