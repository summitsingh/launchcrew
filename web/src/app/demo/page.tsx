import type { Metadata } from 'next';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { Layers } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Fictional demo | LaunchCrew',
  description:
    'A fictional, read-only walkthrough of a LaunchCrew pack. No sign-in, no live data, nothing here is a real business.',
};

type DemoFacts = {
  product?: string;
  price?: string;
  audience?: string;
  channel?: string;
  brand_voice?: string;
  approved_claims?: string[];
  sources?: string[];
};

function loadDemoFacts(): DemoFacts {
  try {
    const raw = readFileSync(join(process.cwd(), 'public', 'facts', 'demo_facts.json'), 'utf8');
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? (parsed as DemoFacts) : {};
  } catch {
    return {};
  }
}

const STEPS: Array<[string, string]> = [
  ['Scout', 'Reads only the confirmed facts below. Nothing else enters the draft.'],
  ['Maker', 'Drafts the launch post and email from those facts alone.'],
  ['Checker', 'Blocks any claim the facts do not support, before you ever see it.'],
  ['You', 'Review the exact version, approve it, and export or publish it.'],
];

export default function DemoPage() {
  const facts = loadDemoFacts();
  const claims = Array.isArray(facts.approved_claims) ? facts.approved_claims.filter(item => typeof item === 'string') : [];
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="LaunchCrew home"><span className="brand-mark"><Layers size={21} /></span>LaunchCrew</a>
        <div className="workspace">FICTIONAL DEMO</div>
        <nav aria-label="Site">
          <a href="/">Review desk</a>
          <a href="/plans">Plans</a>
        </nav>
      </aside>
      <div className="main-wrap">
        <main id="main">
          <div className="page-intro">
            <div>
              <p className="eyebrow">FICTIONAL DEMO / READ ONLY</p>
              <h1>Watch a fictional launch take shape.</h1>
              <p className="lede">Everything below is invented for demonstration. No sign-in, no live data, nothing here is a real business, and nothing on this page can publish anything.</p>
            </div>
            <span className="step-label">DEMO</span>
          </div>

          <section aria-label="Fictional facts" className="panel" data-testid="demo-facts">
            <p className="eyebrow">THE FICTIONAL FACTS</p>
            <h2>Scout starts here, and only here.</h2>
            <dl>
              <div><dt>Product</dt><dd>{facts.product || 'Vegan leather wallet'}</dd></div>
              <div><dt>Price</dt><dd>{facts.price || '$49'}</dd></div>
              <div><dt>Audience</dt><dd>{facts.audience || 'Austin commuters'}</dd></div>
              <div><dt>Channel</dt><dd>{facts.channel || 'Instagram'}</dd></div>
              <div><dt>Voice</dt><dd>{facts.brand_voice || 'Warm, plain, no hype'}</dd></div>
            </dl>
            <h3>Approved claims</h3>
            <ul>
              {claims.map(claim => <li key={claim}>{claim}</li>)}
            </ul>
            <p className="hint">Source: facts/demo_facts.json. Fictional input for demonstration, not a real business.</p>
          </section>

          <section aria-label="How a pack takes shape" className="panel">
            <p className="eyebrow">THE FOUR STEPS</p>
            <h2>From facts to a launch pack.</h2>
            <ol>
              {STEPS.map(([title, text], i) => (
                <li key={title}><strong>{i + 1}. {title}</strong><p className="hint">{text}</p></li>
              ))}
            </ol>
          </section>

          <section aria-label="The approval rule" className="panel">
            <p className="eyebrow">THE APPROVAL RULE</p>
            <h2>Nothing publishes without your approval.</h2>
            <p>Every pack passes the Ready gate: you approve the exact version, the server rechecks that exact text at publish time, and the result lands in a receipt you can inspect. Export works the same way.</p>
            <p className="hint">The live desk needs sign-in so your facts, drafts, and receipts stay yours. This page never touches your data.</p>
          </section>

          <section aria-label="Try the live product" className="panel">
            <p className="eyebrow">NEXT STEP</p>
            <h2>Try it with your own launch.</h2>
            <div className="queue-actions">
              <a href="/" className="button">Open the review desk</a>
              <a href="/plans" className="button outline">See plans</a>
            </div>
          </section>

          <footer className="page-footer">
            <span>LaunchCrew · Fictional demo</span>
            <span><a href="/demo" aria-current="page">Demo</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="/plans">Plans</a></span>
            <a href="https://github.com/summitsingh/launchcrew">Public GitHub repo</a>
          </footer>
        </main>
      </div>
    </div>
  );
}
