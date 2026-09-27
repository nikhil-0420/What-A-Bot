import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Billing({ businessId }: { businessId: string }) {
  const [billingStatus, setBillingStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getBillingStatus(businessId)
      .then(setBillingStatus)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [businessId]);

  const handleTestCheckout = async () => {
    try {
      const data = await api.createCheckout(businessId);
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch {
      alert('Failed to initiate test checkout');
    }
  };

  return (
    <div className="glass-panel">
      <div className="content-header" style={{ marginBottom: '16px' }}>
        <div>
          <h2>Billing & Subscriptions</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
            Retailer software subscription management (separate from customer ordering payments).
          </p>
        </div>
      </div>
      
      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading subscription status...
        </div>
      ) : billingStatus ? (
        <div style={{ background: 'var(--bg-subtle)', padding: '20px', borderRadius: '10px', border: '1px solid var(--border-color)', marginBottom: '20px' }}>
          <p style={{ margin: '0 0 10px 0', fontSize: '14px' }}>
            Current Plan: <span className="badge success" style={{ marginLeft: '8px' }}>{billingStatus.plan || 'Active'}</span>
          </p>
          <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
            Last Updated: {billingStatus.updated_at ? new Date(billingStatus.updated_at).toLocaleString() : 'N/A'}
          </p>
        </div>
      ) : (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-subtle)', borderRadius: '8px', marginBottom: '20px' }}>
          No active subscription plan found.
        </div>
      )}

      <button className="button-primary" onClick={handleTestCheckout}>
        Test Checkout (Dodo Payments) &rarr;
      </button>
    </div>
  );
}
