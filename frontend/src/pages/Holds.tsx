import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Holds({ businessId }: { businessId: string }) {
  const [holds, setHolds] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getHolds(businessId)
      .then(setHolds)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [businessId]);

  return (
    <div className="glass-panel">
      <div className="content-header" style={{ marginBottom: '16px' }}>
        <div>
          <h2>Order Holds</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
            Review orders requiring manual owner approval or inventory confirmation.
          </p>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading held orders...
        </div>
      ) : holds.length === 0 ? (
        <div style={{ padding: '36px', textAlign: 'center', background: 'var(--bg-subtle)', borderRadius: '10px', border: '1px dashed var(--border-color)' }}>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '14px' }}>
            No held orders at the moment. You're all caught up!
          </p>
        </div>
      ) : (
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
                <td style={{ fontWeight: 500 }}>₹{((h.total_paise || 0) / 100).toFixed(2)}</td>
                <td style={{ display: 'flex', gap: '8px' }}>
                  <button
                    style={{ padding: '6px 12px', fontSize: '13px' }}
                    onClick={() => api.resolveHold(businessId, { order_id: h.order_id, approve: true })}
                  >
                    Approve
                  </button>
                  <button
                    className="danger"
                    style={{ padding: '6px 12px', fontSize: '13px' }}
                    onClick={() => api.resolveHold(businessId, { order_id: h.order_id, approve: false })}
                  >
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
