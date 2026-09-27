import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Evidence({ businessId }: { businessId: string }) {
  const [evidence, setEvidence] = useState<any>(null);

  useEffect(() => {
    api.getEvidence(businessId).then(setEvidence).catch(console.error);
  }, [businessId]);

  return (
    <div className="glass-panel">
      <h2>Transaction Evidence Panel</h2>
      <p style={{ color: 'var(--text-muted)' }}>Real-time transparency into the AI's internal decisions.</p>
      {evidence ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginTop: '24px' }}>
          <div style={{ background: 'var(--bg-surface)', padding: '24px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Agent Trace ({evidence.trace_id})</h3>
            <p style={{ margin: '8px 0' }}><strong>Latency:</strong> {evidence.latency_ms} ms</p>
            <p style={{ margin: '8px 0' }}><strong>Cost:</strong> ${evidence.cost_usd}</p>
            <p style={{ margin: '8px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong>Outbox State:</strong> <span className="badge success">{evidence.outbox_state}</span>
            </p>
            <p style={{ margin: '8px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong>Order Status:</strong> <span className="badge">{evidence.order_status}</span>
            </p>
          </div>
          <div style={{ background: 'var(--bg-surface)', padding: '24px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Constraints & Validation</h3>
            <pre>
{JSON.stringify(evidence.normalized_constraints, null, 2)}
            </pre>
            <p style={{ margin: '16px 0 8px 0' }}><strong>Validation:</strong> {evidence.validation_result}</p>
            <h4 style={{ fontSize: '13px', marginTop: '16px' }}>Stock Before/After</h4>
            <pre>
{JSON.stringify(evidence.stock_before_after, null, 2)}
            </pre>
          </div>
        </div>
      ) : (
        <p>Loading evidence...</p>
      )}
    </div>
  );
}
