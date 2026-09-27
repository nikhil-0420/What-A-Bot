import React, { useState } from 'react';
import { api } from '../api/client';

export default function Register({ navigate }: { navigate: (route: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      const { token } = await api.register({ email, password });
      localStorage.setItem('token', token);
      navigate('businesses');
    } catch (err: any) {
      setError(err?.message || 'Registration failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-panel" style={{ margin: '40px auto' }}>
      <div className="login-form-wrap">
        <p className="eyebrow">NEW OWNER ACCESS</p>
        <h2>Create owner account</h2>
        <p className="form-intro">Set up credentials to manage your What-A-Bot stores.</p>

        {error && (
          <div style={{ padding: '10px 14px', background: 'var(--danger-light)', color: 'var(--danger)', borderRadius: '8px', fontSize: '13px', marginBottom: '14px', border: '1px solid var(--danger-border)' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleRegister} className="portal-form">
          <div>
            <label htmlFor="reg-email" style={{ display: 'block', marginBottom: '6px' }}>Work email</label>
            <input
              id="reg-email"
              type="email"
              placeholder="owner@yourshop.in"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="reg-pass" style={{ display: 'block', marginBottom: '6px' }}>Password</label>
            <input
              id="reg-pass"
              type="password"
              placeholder="Choose a secure password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="reg-confirm-pass" style={{ display: 'block', marginBottom: '6px' }}>Confirm password</label>
            <input
              id="reg-confirm-pass"
              type="password"
              placeholder="Re-enter password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              required
            />
          </div>
          <button className="button-primary login-submit" type="submit" disabled={submitting}>
            {submitting ? 'Creating account...' : 'Create Account \u2192'}
          </button>
        </form>

        <div style={{ marginTop: '20px', textAlign: 'center' }}>
          <a
            href="#login"
            onClick={(e) => { e.preventDefault(); navigate('login'); }}
            style={{ color: 'var(--primary)', fontSize: '13.5px', textDecoration: 'none', fontWeight: 500 }}
          >
            Already have an account? Sign in &rarr;
          </a>
        </div>
      </div>
    </div>
  );
}
