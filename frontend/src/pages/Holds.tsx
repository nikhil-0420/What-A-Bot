import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Holds({ businessId }: { businessId: string }) {
  const [holds, setHolds] = useState<any[]>([]);

  useEffect(() => {
    api.getHolds(businessId).then(setHolds).catch(console.error);
  }, [businessId]);

  return (
    <div className="glass-panel">
      <h2>Held Orders</h2>
      {holds.length === 0 ? <p style={{ color: 'var(--text-muted)' }}>No held orders at the moment. You're all caught up!</p> : (
        <table>
          <thead>
            <tr>
              <th>Order ID</th>
              <th>Status</th>
              <th>Total</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {holds.map(h => (
              <tr key={h.order_id}>
                <td><span className="badge">{h.order_id}</span></td>
                <td><span className="badge pending">{h.status}</span></td>
                <td style={{ fontWeight: 500 }}>₹{(h.total_paise / 100).toFixed(2)}</td>
                <td style={{ display: 'flex', gap: '8px' }}>
                  <button onClick={() => api.resolveHold(businessId, { order_id: h.order_id, approve: true })}>Approve</button>
                  <button className="danger" onClick={() => api.resolveHold(businessId, { order_id: h.order_id, approve: false })}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
