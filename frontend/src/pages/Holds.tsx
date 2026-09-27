import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Holds({ businessId }: { businessId: string }) {
  const [holds, setHolds] = useState<any[]>([]);

  const loadHolds = () => {
    api.getHolds(businessId).then(setHolds).catch(console.error);
  };

  useEffect(() => {
    loadHolds();
  }, [businessId]);

  const handleResolve = async (orderId: string, approve: boolean) => {
    try {
      await api.resolveHold(businessId, { order_id: orderId, approve });
      loadHolds();
    } catch (err: any) {
      alert("Failed to resolve hold: " + (err?.message || "Unknown error"));
    }
  };

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
                  <button onClick={() => handleResolve(h.order_id, true)}>Approve</button>
                  <button className="danger" onClick={() => handleResolve(h.order_id, false)}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
