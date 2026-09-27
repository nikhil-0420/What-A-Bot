import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function BusinessPicker({ navigate }: { navigate: (route: string) => void }) {
  const [businesses, setBusinesses] = useState<any[]>([]);

  useEffect(() => {
    api.getBusinesses().then(setBusinesses).catch(console.error);
  }, []);

  return (
    <div className="business-picker glass-panel">
      <h2>Select a Business</h2>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {businesses.map(b => (
          <li key={b.business_id}>
            <button onClick={() => navigate(`dashboard/${b.business_id}`)}>
              {b.name} <span className="badge">{b.business_type}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
