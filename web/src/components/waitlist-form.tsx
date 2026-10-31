'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { PLANS, isValidWaitlistEmail, submitWaitlist, type PlanTier } from '@/lib/plans';

async function postWaitlist(url: string, body: unknown) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  return { status: response.status, body: parsed };
}

export function WaitlistForm({ defaultTier = 'pro' }: { defaultTier?: PlanTier }) {
  const [email, setEmail] = useState('');
  const [interest, setInterest] = useState('');
  const [tier, setTier] = useState<PlanTier>(defaultTier);
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const emailValid = email.trim() === '' || isValidWaitlistEmail(email);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (status === 'sending') return;
    setStatus('sending');
    setMessage('');
    const result = await submitWaitlist({ email, interest, tier }, postWaitlist);
    setStatus(result.ok ? 'done' : 'error');
    setMessage(result.message);
  }

  return (
    <form onSubmit={onSubmit} aria-label="Waitlist signup">
      <label htmlFor="waitlist-email">Email</label>
      <input
        id="waitlist-email"
        type="email"
        value={email}
        onChange={e => setEmail(e.target.value)}
        required
        maxLength={254}
        autoComplete="email"
        placeholder="you@example.com"
      />
      {!emailValid && <p role="alert">Enter a valid email address.</p>}
      <label htmlFor="waitlist-interest">What are you launching (optional)</label>
      <input
        id="waitlist-interest"
        value={interest}
        onChange={e => setInterest(e.target.value)}
        maxLength={120}
        placeholder="General launch updates"
      />
      <label htmlFor="waitlist-tier">Plan interest</label>
      <select id="waitlist-tier" value={tier} onChange={e => setTier(e.target.value as PlanTier)}>
        {PLANS.map(plan => (
          <option key={plan.tier} value={plan.tier}>{plan.name}</option>
        ))}
      </select>
      <Button type="submit" disabled={status === 'sending'}>
        {status === 'sending' ? 'Joining...' : 'Join the waitlist'}
      </Button>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
