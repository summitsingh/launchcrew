import type { Metadata } from 'next';
import { Layers } from 'lucide-react';
import { ABOUT_MISSION, CHECKER_UNMETERED_NOTE, PLANS, demoVideoUrl } from '@/lib/plans';
import { WaitlistForm } from '@/components/waitlist-form';

export const metadata: Metadata = {
  title: 'Plans | LaunchCrew',
  description: 'Free, Pro, and Team plans. Checker safety verification stays unmetered on every tier.',
};

export default function PlansPage() {
  const videoUrl = demoVideoUrl();
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="LaunchCrew home"><span className="brand-mark"><Layers size={21} /></span>LaunchCrew</a>
        <div className="workspace">PLANS</div>
        <nav aria-label="Site">
          <a href="/">Review desk</a>
          <a href="/plans" aria-current="page">Plans</a>
        </nav>
      </aside>
      <div className="main-wrap">
        <main id="main">
          <div className="page-intro">
            <div>
              <p className="eyebrow">LAUNCHCREW / PLANS</p>
              <h1>Plans for every stage of launch.</h1>
              <p className="lede">Start free, grow into Pro, collaborate on Team. {CHECKER_UNMETERED_NOTE}</p>
            </div>
            <span className="step-label">PLANS</span>
          </div>

          <section aria-label="Plans">
            <div className="two-column equal">
              {PLANS.map(plan => (
                <article key={plan.tier} className="panel" data-testid={`plan-${plan.tier}`}>
                  <p className="eyebrow">{plan.price}</p>
                  <h2>{plan.name}</h2>
                  <p className="hint">{plan.audience}</p>
                  <ul>
                    {plan.features.map(feature => <li key={feature}>{feature}</li>)}
                  </ul>
                </article>
              ))}
            </div>
            <p className="hint" data-testid="checker-unmetered-note">{CHECKER_UNMETERED_NOTE}</p>
          </section>

          <section aria-label="About LaunchCrew" className="panel" data-testid="about-section">
            <p className="eyebrow">ABOUT</p>
            <h2>About LaunchCrew</h2>
            <p>{ABOUT_MISSION}</p>
          </section>

          <section aria-label="Demo video" className="panel" data-testid="demo-slot">
            <p className="eyebrow">DEMO</p>
            <h2>See LaunchCrew in action</h2>
            {videoUrl ? (
              <a href={videoUrl} data-testid="demo-link">Watch the demo video</a>
            ) : (
              <p className="hint" data-testid="demo-placeholder">A demo video link will appear here once it is published.</p>
            )}
          </section>

          <section aria-label="Join the waitlist" className="panel" data-testid="waitlist-section">
            <p className="eyebrow">WAITLIST</p>
            <h2>Join the waitlist</h2>
            <p className="hint">Leave your email and the plan you are interested in. One signup per email.</p>
            <WaitlistForm />
          </section>

          <footer className="page-footer">
            <span>LaunchCrew · Demo workspace</span>
            <span><a href="/plans">Plans</a> · <a href="/">Review desk</a></span>
            <a href="https://github.com/summitsingh/launchcrew">Public GitHub repo</a>
          </footer>
        </main>
      </div>
    </div>
  );
}
