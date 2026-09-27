import React, { useState } from 'react';
import { api } from '../api/client';

export default function Register({ navigate }: { navigate: (route: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      alert("Passwords don't match!");
      return;
    }
    try {
      const { token } = await api.register({ email, password });
      localStorage.setItem('token', token);
      navigate('businesses');
    } catch (err) {
      alert('Registration failed');
    }
  };

  return (
    <div className="login-page glass-panel">
      <h2>Owner Registration</h2>
      <form onSubmit={handleRegister}>
        <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
        <input type="password" placeholder="Confirm Password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required />
        <button type="submit">Create Account</button>
      </form>
      <div style={{ marginTop: '16px', textAlign: 'center' }}>
        <a href="#login" onClick={(e) => { e.preventDefault(); navigate('login'); }} style={{ color: 'var(--text-muted)', fontSize: '14px' }}>
          Already have an account? Login here.
        </a>
      </div>
    </div>
  );
}
