import type { Metadata } from 'next';
import { Layers } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Terms of Service | LaunchCrew',
  description:
    'The terms for using LaunchCrew: the service, owner responsibilities, the approval model, and liability limits.',
};

export default function TermsPage() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="LaunchCrew home"><span className="brand-mark"><Layers size={21} /></span>LaunchCrew</a>
        <div className="workspace">TERMS</div>
        <nav aria-label="Site">
          <a href="/">Review desk</a>
          <a href="/plans">Plans</a>
        </nav>
      </aside>
      <div className="main-wrap">
        <main id="main">
          <div className="page-intro">
            <div>
              <p className="eyebrow">LAUNCHCREW / TERMS</p>
              <h1>Terms of Service</h1>
              <p className="lede">The rules for using LaunchCrew, in plain language.</p>
            </div>
            <span className="step-label">TERMS</span>
          </div>

          <p className="hint">Last updated: November 3, 2026</p>

          <section aria-label="The service" className="panel">
            <p className="eyebrow">SERVICE</p>
            <h2>The service</h2>
            <p>
              LaunchCrew is a web app that helps solo founders create launch content. You confirm
              product facts, three agents (Scout, Maker, and Checker) draft and audit content, you
              approve an exact version, and approved content can be exported or published to your
              connected social accounts.
            </p>
          </section>

          <section aria-label="Accounts and eligibility" className="panel">
            <p className="eyebrow">ACCOUNTS</p>
            <h2>Accounts and eligibility</h2>
            <p>
              You sign in with Google or Facebook OAuth. You must be able to form a binding
              agreement where you live, and you are responsible for keeping your sign-in and any
              connected account credentials secure.
            </p>
          </section>

          <section aria-label="Owner responsibilities" className="panel">
            <p className="eyebrow">RESPONSIBILITY</p>
            <h2>Owner responsibilities</h2>
            <p>
              You are responsible for the claims in your facts and for the content you approve and
              publish. The Checker blocks unsupported claims before review, but it cannot verify
              the real world: confirm that your facts are true before you approve anything.
            </p>
          </section>

          <section aria-label="Approval model" className="panel">
            <p className="eyebrow">APPROVAL</p>
            <h2>The approval model</h2>
            <p>
              Nothing publishes without your approval of the exact version. Publishing runs through
              the Ready gate: a pack publishes only after you approve its current revision, the
              server rechecks the exact text at publish time, and the result is recorded in a
              receipt. Export works the same way.
            </p>
          </section>

          <section aria-label="Acceptable use" className="panel">
            <p className="eyebrow">USE</p>
            <h2>Acceptable use</h2>
            <p>You agree not to:</p>
            <ul>
              <li>Publish content you know to be false, misleading, or infringing.</li>
              <li>Connect accounts you do not own or lack permission to publish to.</li>
              <li>Abuse, overload, or probe the service, or try to bypass its approval gates.</li>
              <li>Use the service to spam any platform or violate any platform policy.</li>
            </ul>
          </section>

          <section aria-label="Intellectual property" className="panel">
            <p className="eyebrow">OWNERSHIP</p>
            <h2>Intellectual property</h2>
            <p>
              You keep ownership of your content. LaunchCrew claims no rights beyond operating the
              service: running your drafts through generation, checking, and publishing at your
              direction. The service name, design, and code remain ours.
            </p>
          </section>

          <section aria-label="Third-party services" className="panel">
            <p className="eyebrow">THIRD PARTIES</p>
            <h2>Third-party services</h2>
            <p>
              Sign-in, model generation, Drive import, and social publishing depend on third-party
              services (Google, Meta, and the social platforms you connect). Those services are
              governed by their own terms and policies, and outages or policy changes on their
              side can limit what LaunchCrew can do for you.
            </p>
          </section>

          <section aria-label="Availability and warranty" className="panel">
            <p className="eyebrow">BETA</p>
            <h2>Availability and warranty</h2>
            <p>
              LaunchCrew is a hackathon beta. It may change, pause, or stop without notice, and it
              comes with no warranty: to the extent the law allows, the service is provided as is,
              without promises of accuracy, uptime, or fitness for any purpose.
            </p>
          </section>

          <section aria-label="Limitation of liability" className="panel">
            <p className="eyebrow">LIABILITY</p>
            <h2>Limitation of liability</h2>
            <p>
              To the extent the law allows, we are not liable for indirect or consequential losses
              from your use of the service, including losses from content you approved and
              published. Our total liability for any claim is limited to what you paid us, and
              there is currently no paid plan, so that limit is zero.
            </p>
          </section>

          <section aria-label="Changes to these terms" className="panel">
            <p className="eyebrow">CHANGES</p>
            <h2>Changes to these terms</h2>
            <p>
              If these terms change, we will update the date above. Material changes will be
              announced in the product before they take effect, and continued use after that point
              means you accept the updated terms.
            </p>
          </section>

          <section aria-label="Contact" className="panel">
            <p className="eyebrow">CONTACT</p>
            <h2>Contact</h2>
            <p>For questions about these terms: summitsingh5@gmail.com</p>
          </section>

          <footer className="page-footer">
            <span>LaunchCrew</span>
            <span><a href="/privacy">Privacy</a> · <a href="/terms" aria-current="page">Terms</a> · <a href="/plans">Plans</a></span>
            <a href="https://github.com/summitsingh/launchcrew">Public GitHub repo</a>
          </footer>
        </main>
      </div>
    </div>
  );
}
