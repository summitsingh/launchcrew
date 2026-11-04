import type { Metadata } from 'next';
import { Layers } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Privacy Policy | LaunchCrew',
  description:
    'How LaunchCrew collects, uses, stores, and deletes your data, including model processing and owner-initiated integrations.',
};

export default function PrivacyPage() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="LaunchCrew home"><span className="brand-mark"><Layers size={21} /></span>LaunchCrew</a>
        <div className="workspace">PRIVACY</div>
        <nav aria-label="Site">
          <a href="/">Review desk</a>
          <a href="/plans">Plans</a>
        </nav>
      </aside>
      <div className="main-wrap">
        <main id="main">
          <div className="page-intro">
            <div>
              <p className="eyebrow">LAUNCHCREW / PRIVACY</p>
              <h1>Privacy Policy</h1>
              <p className="lede">What we collect, how we use it, and how you can delete it.</p>
            </div>
            <span className="step-label">PRIVACY</span>
          </div>

          <p className="hint">Last updated: November 3, 2026</p>

          <section aria-label="What we collect" className="panel">
            <p className="eyebrow">COLLECTION</p>
            <h2>What we collect</h2>
            <p>LaunchCrew collects only what it needs to run the service:</p>
            <ul>
              <li>Account identity: the profile and email address returned by the sign-in provider you choose (Google or Facebook OAuth, profile and email scopes only).</li>
              <li>Owner-provided facts and content: the product facts you confirm, drafts you write or edit, approvals, schedules, and publishing receipts.</li>
              <li>Connection tokens: access tokens you provide or authorize for owner-initiated integrations, described below.</li>
              <li>Usage records needed to run the service: run history, checker verdicts, and session records.</li>
            </ul>
          </section>

          <section aria-label="How we use it" className="panel">
            <p className="eyebrow">USE</p>
            <h2>How we use it</h2>
            <p>
              We use your data to operate LaunchCrew: to sign you in, to generate drafts from your
              confirmed facts, to audit those drafts against your facts, to record your approvals,
              and to publish only the exact versions you approve to the accounts you connect.
            </p>
          </section>

          <section aria-label="Model processing" className="panel">
            <p className="eyebrow">MODELS</p>
            <h2>Model processing</h2>
            <p>
              Content you submit is sent to the Meta Model API (Muse Spark) to generate drafts and
              to check them against your confirmed facts. If you use the optional photo check, the
              photo is processed for segmentation. We do not use your content to train models.
            </p>
          </section>

          <section aria-label="Integrations" className="panel">
            <p className="eyebrow">INTEGRATIONS</p>
            <h2>Integrations</h2>
            <p>Every integration is owner-initiated and optional:</p>
            <ul>
              <li>Google Drive import: you pick files; the app reads only the files you select.</li>
              <li>Social connections (Instagram today): you provide or authorize an access token, which is stored encrypted and used only to publish owner-approved content and to verify the result.</li>
            </ul>
            <p>You can disconnect any integration at any time.</p>
          </section>

          <section aria-label="Storage and security" className="panel">
            <p className="eyebrow">SECURITY</p>
            <h2>Storage and security</h2>
            <p>
              Data lives in the app Postgres database and AWS infrastructure in us-east-1.
              Social connection tokens are encrypted at rest and are never returned in API responses,
              logs, UI payloads, or receipts. The Drive Picker token is different by design: it is a
              short-lived, one-time token handed to your signed-in browser only to complete the file
              pick you started. It lives in server memory only until claimed or expired and is never
              written to the database, logs, or receipts. Sign-in uses an opaque session cookie backed by
              server-side sessions.
            </p>
          </section>

          <section aria-label="Data sharing" className="panel">
            <p className="eyebrow">SHARING</p>
            <h2>Data sharing</h2>
            <p>
              We do not sell personal data and we run no third-party advertising. Data is shared
              only with the service providers needed to run the product (hosting and the model
              API named above) and with the platforms you explicitly connect.
            </p>
          </section>

          <section aria-label="Retention and deletion" className="panel">
            <p className="eyebrow">RETENTION</p>
            <h2>Retention and deletion</h2>
            <p>
              You can request deletion of your data at any time by contacting us at the address
              below, and you can disconnect integrations yourself at any time, which removes the
              stored token while keeping your past approvals and exports intact.
            </p>
          </section>

          <section aria-label="Cookies and sessions" className="panel">
            <p className="eyebrow">COOKIES</p>
            <h2>Cookies and sessions</h2>
            <p>
              LaunchCrew sets a single session cookie that holds an opaque session identifier. It
              is HttpOnly, Secure, and SameSite Lax, and it expires with your session. Your theme
              choice is stored locally in your own browser, not in a cookie. There is no
              third-party tracking on this site.
            </p>
          </section>

          <section aria-label="Changes to this policy" className="panel">
            <p className="eyebrow">CHANGES</p>
            <h2>Changes to this policy</h2>
            <p>
              If this policy changes, we will update the date above and note the change here.
              Material changes will be announced in the product before they take effect.
            </p>
          </section>

          <section aria-label="Contact" className="panel">
            <p className="eyebrow">CONTACT</p>
            <h2>Contact</h2>
            <p>For privacy questions or deletion requests: summitsingh5@gmail.com</p>
          </section>

          <footer className="page-footer">
            <span>LaunchCrew</span>
            <span><a href="/privacy" aria-current="page">Privacy</a> · <a href="/terms">Terms</a> · <a href="/plans">Plans</a> · <a href="/demo">Demo</a></span>
            <a href="https://github.com/summitsingh/launchcrew">Public GitHub repo</a>
          </footer>
        </main>
      </div>
    </div>
  );
}
