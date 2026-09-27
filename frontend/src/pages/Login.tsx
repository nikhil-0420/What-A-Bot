import React, { useState } from 'react';
import { api } from '../api/client';

export default function Login({ navigate }: { navigate: (route: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const { token } = await api.login({ email, password });
      localStorage.setItem('token', token);
      navigate('businesses');
    } catch (err) {
      alert('Login failed');
    }
  };

  return (
    <div className="login-page glass-panel">
      <h2>Owner Login</h2>
      <form onSubmit={handleLogin}>
        <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
        <button type="submit">Log in to Dashboard</button>
      </form>
      <div style={{ marginTop: '16px', textAlign: 'center' }}>
        <a href="#register" onClick={(e) => { e.preventDefault(); navigate('register'); }} style={{ color: 'var(--text-muted)', fontSize: '14px' }}>
          Don't have an account? Register here.
        </a>
      </div>
    </div>
  );
}
