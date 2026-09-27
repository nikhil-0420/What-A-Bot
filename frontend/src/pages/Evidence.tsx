import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Evidence({ businessId }: { businessId: string }) {
  const [evidence, setEvidence] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getEvidence(businessId)
      .then(setEvidence)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [businessId]);

  return (
    <div className="glass-panel">
      <div className="content-header" style={{ marginBottom: '16px' }}>
        <div>
          <h2>AI Evidence Panel</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
            Real-time audit trail and latency telemetry for autonomous AI customer interactions.
          </p>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading AI transaction evidence...
        </div>
      ) : evidence ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px', marginTop: '16px' }}>
          <div style={{ background: 'var(--bg-subtle)', padding: '20px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 16px 0' }}>
              Agent Trace ({evidence.trace_id || 'N/A'})
            </h3>
            <p style={{ margin: '8px 0', fontSize: '14px' }}><strong>Latency:</strong> {evidence.latency_ms ?? 0} ms</p>
            <p style={{ margin: '8px 0', fontSize: '14px' }}><strong>Cost:</strong> ${evidence.cost_usd ?? '0.00'}</p>
            <p style={{ margin: '8px 0', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong>Outbox State:</strong> <span className="badge success">{evidence.outbox_state || 'idle'}</span>
            </p>
            <p style={{ margin: '8px 0', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong>Order Status:</strong> <span className="badge">{evidence.order_status || 'normal'}</span>
            </p>
          </div>
          <div style={{ background: 'var(--bg-subtle)', padding: '20px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 16px 0' }}>
              Constraints & Validation
            </h3>
            <pre>
{JSON.stringify(evidence.normalized_constraints || {}, null, 2)}
            </pre>
            <p style={{ margin: '14px 0 6px 0', fontSize: '14px' }}><strong>Validation:</strong> {evidence.validation_result || 'N/A'}</p>
            <h4 style={{ fontSize: '12px', marginTop: '14px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Stock Before / After
            </h4>
            <pre>
{JSON.stringify(evidence.stock_before_after || {}, null, 2)}
            </pre>
          </div>
        </div>
      ) : (
        <div style={{ padding: '36px', textAlign: 'center', background: 'var(--bg-subtle)', borderRadius: '10px', border: '1px dashed var(--border-color)' }}>
          <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '14px' }}>
            No trace evidence recorded yet for this session.
          </p>
        </div>
      )}
    </div>
  );
}
