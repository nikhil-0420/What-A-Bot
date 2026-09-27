import { useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, api, setAuthToken } from '../api/client';
import AlertBanner from '../components/AlertBanner';
import '../components/portal.css';

type LoginProps = {
  onLogin: () => void;
};

export default function Login({ onLogin }: LoginProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const result = await api.login({ email: email.trim(), password });
      setAuthToken(result.token, email.trim());
      onLogin();
    } catch (cause) {
      setError({
        message: cause instanceof ApiError ? cause.message : 'Sign-in failed. Please try again.',
        code: cause instanceof ApiError ? cause.code : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="portal-login">
      <section className="login-story" aria-label="What-A-Bot retailer portal">
        <span className="login-brand__mark" aria-hidden="true">
          <span className="material-symbols-outlined">smart_toy</span>
        </span>
        <span className="login-brand__chip"><i />WHAT-A-BOT COCKPIT</span>
        <h1>Retailer Portal Login</h1>
        <p className="story-description">Manage your shop's WhatsApp ordering assistant.</p>
      </section>

      <section className="login-panel">
        <div className="login-form-wrap">
          <p className="eyebrow">OWNER ACCESS</p>
          <h2>Sign in to your shop</h2>
          <p className="form-intro">Use the owner account connected to your business.</p>
          <form onSubmit={handleSubmit} className="portal-form">
            <div className="login-field-heading">
              <label htmlFor="owner-email">Work email</label>
              <span>OWNER ACCOUNT</span>
            </div>
            <div className="login-input-control">
              <span className="material-symbols-outlined" aria-hidden="true">alternate_email</span>
              <input
                id="owner-email"
                name="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="owner@yourshop.in"
                required
              />
            </div>
            <div className="label-row">
              <label htmlFor="owner-password">Password</label>
              <span>STORE ACCESS</span>
            </div>
            <div className="login-password-control">
              <span className="material-symbols-outlined" aria-hidden="true">key</span>
              <input
                id="owner-password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter your password"
                required
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
            {error && (
              <AlertBanner
                title="Could not sign in"
                message={error.message}
                code={error.code}
                onDismiss={() => setError(null)}
              />
            )}
            <button className="button button-primary login-submit" type="submit" disabled={submitting}>
              {submitting ? <><span className="button-spinner" />Signing in</> : <>Continue <span aria-hidden="true">&#8594;</span></>}
            </button>
          </form>
          <p className="secure-note"><span aria-hidden="true">&#9679;</span> Your account only shows businesses you own.</p>
        </div>
        <footer className="login-footer">EMBERGROUND <span>OWNER WORKSPACE</span></footer>
      </section>
      <p className="login-preview-note">Secure access for your shop's owner account</p>
    </main>
  );
}
