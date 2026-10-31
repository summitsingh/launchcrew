export type PlanTier = 'free' | 'pro' | 'team';

export interface Plan {
  tier: PlanTier;
  name: string;
  price: string;
  audience: string;
  features: string[];
}

export const PLANS: Plan[] = [
  {
    tier: 'free',
    name: 'Free',
    price: 'Free',
    audience: 'Individual evaluation and solo founders trying LaunchCrew on one brand.',
    features: [
      'One brand workspace with explicit product facts',
      'Maker drafts grounded in confirmed facts only',
      'Checker safety verification on every draft, unmetered',
      'Individual approval and receipt export',
    ],
  },
  {
    tier: 'pro',
    name: 'Pro',
    price: 'Pro',
    audience: 'Growing brands shipping launches every week with voice and channel variants.',
    features: [
      'Everything in Free, for higher launch volume',
      'Saved voice profiles with banned-term enforcement',
      'Channel variants and landing-page parity checks',
      'Campaign weeks with per-day approval',
    ],
  },
  {
    tier: 'team',
    name: 'Team',
    price: 'Team',
    audience: 'Multi-seat collaboration with shared brand memory across seats.',
    features: [
      'Everything in Pro, for multiple seats',
      'Shared brand memory and facts library across the team',
      'Per-seat approval attribution on every receipt',
      'Workspace-scoped runs, memory, and outcomes',
    ],
  },
];

export const CHECKER_UNMETERED_NOTE =
  'Checker safety verification stays unmetered on every tier: every draft is fully checked with no usage limits.';

export const ABOUT_MISSION =
  'LaunchCrew is a deterministic, fact-grounded launch copilot for e-commerce and founders. ' +
  'Every draft is built only from explicitly confirmed product facts, the Checker blocks ' +
  'unsupported claims before you review, and nothing auto-posts or publishes. ' +
  'No hallucinations, no invented claims, and platform policy compliance stays enforced on every draft.';

export function demoVideoUrl(): string {
  return (process.env.NEXT_PUBLIC_DEMO_VIDEO_URL || '').trim();
}

export function isValidWaitlistEmail(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized || normalized.length > 254 || normalized.includes(' ')) return false;
  const parts = normalized.split('@');
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  if (!local || !domain.includes('.')) return false;
  return true;
}

export async function submitWaitlist(
  input: { email: string; interest: string; tier: PlanTier },
  post: (url: string, body: unknown) => Promise<{ status: number; body: unknown }>,
): Promise<{ ok: boolean; duplicate: boolean; message: string }> {
  const email = input.email.trim().toLowerCase();
  if (!isValidWaitlistEmail(email)) {
    return { ok: false, duplicate: false, message: 'Enter a valid email address.' };
  }
  let response: { status: number; body: unknown };
  try {
    response = await post('/api/waitlist', { email, interest: input.interest.trim() || 'general', tier: input.tier });
  } catch {
    return { ok: false, duplicate: false, message: 'Signup failed. Try again.' };
  }
  if (response.status === 201) return { ok: true, duplicate: false, message: 'You are on the waitlist.' };
  if (response.status === 200) return { ok: true, duplicate: true, message: 'This email is already on the waitlist.' };
  const detail = response.body && typeof response.body === 'object'
    ? String((response.body as { detail?: unknown }).detail || '')
    : '';
  return { ok: false, duplicate: false, message: detail || 'Signup failed. Try again.' };
}
