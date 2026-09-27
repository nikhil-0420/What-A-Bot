import { useState } from 'react';
import { ApiError, api } from '../api/client';
import type { BotLink as BotLinkData, Business } from '../api/client';
import AlertBanner from '../components/AlertBanner';
import Header from '../components/Header';
import '../components/portal.css';

type BotLinkProps = {
  business?: Business;
  businessId?: string;
  onBack?: () => void;
};

function formatExpiry(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' }).format(date);
}

export default function BotLink({ business, businessId, onBack }: BotLinkProps) {
  const activeBusinessId = business?.business_id || businessId || '';
  const businessName = business?.name || activeBusinessId || 'Your Shop';
  const [link, setLink] = useState<BotLinkData | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);

  async function createLink() {
    setError('');
    setCopied(false);
    setWorking(true);
    try {
      setLink(await api.createBotLink(activeBusinessId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not create a bot link. Please try again.');
    } finally {
      setWorking(false);
    }
  }

  async function copyLink() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.deep_link_url);
      setCopied(true);
    } catch {
      setError('Clipboard access is unavailable. Select and copy the link manually.');
    }
  }

  return (
    <main className="link-page">
      {onBack && <Header title={businessName} showBack onBack={onBack} />}

      <section className="link-content">
        <p className="eyebrow">{businessName.toUpperCase()} <span> / </span> BOT CONNECTION</p>
        <h1>Connect your shop</h1>
        <p className="picker-intro">Create a one-time setup link for this business.</p>

        <div className="link-instructions">
          <div className="instruction-row"><span>01</span><p>Generate a secure, single-use link.</p></div>
          <div className="instruction-row"><span>02</span><p>Open it on the WhatsApp or Telegram account you want to connect.</p></div>
          <div className="instruction-row"><span>03</span><p>Press <strong>/start</strong> in the chat to bind the session before it expires.</p></div>
        </div>

        {link ? (
          <div className="generated-link" aria-live="polite">
            <div className="link-state"><span className="status-dot" />LINK READY <span className="expiry">Expires {formatExpiry(link.expires_at)} IST</span></div>
            <label htmlFor="generated-url">One-time connection link</label>
            <div className="copy-field">
              <input id="generated-url" value={link.deep_link_url} readOnly onFocus={(event) => event.currentTarget.select()} />
              <button className="button button-secondary" type="button" onClick={copyLink}>{copied ? 'Copied' : 'Copy link'}</button>
              <a href={link.deep_link_url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <button className="button button-primary" type="button" style={{ background: 'var(--color-secondary, #006c4a)' }}>Open</button>
              </a>
            </div>
            <p className="link-warning">
              This link works once and expires after 10 minutes. Click the link and send /start in Telegram/WhatsApp to activate your session.
            </p>
            <button className="text-button regenerate-button" type="button" onClick={createLink} disabled={working}>
              {working ? 'Generating...' : 'Generate a fresh link'}
            </button>
          </div>
        ) : (
          <button className="button button-primary generate-button" type="button" onClick={createLink} disabled={working}>
            {working ? <><span className="button-spinner" />Creating secure link</> : <>Generate connection link <span aria-hidden="true">&#8594;</span></>}
          </button>
        )}
        {error && (
          <AlertBanner
            title="Connection link issue"
            message={error}
            onRetry={link ? undefined : createLink}
            onDismiss={() => setError('')}
          />
        )}
      </section>
    </main>
  );
}
