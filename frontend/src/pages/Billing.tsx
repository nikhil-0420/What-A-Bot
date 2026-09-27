import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Billing({ businessId }: { businessId: string }) {
  const [billingStatus, setBillingStatus] = useState<any>(null);

  useEffect(() => {
    api.getBillingStatus(businessId).then(setBillingStatus).catch(console.error);
  }, [businessId]);

  const handleTestCheckout = async () => {
    try {
      const data = await api.createCheckout(businessId);
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch (err) {
      alert('Failed to initiate test checkout');
    }
  };

  return (
    <div>
      <h2>Billing (Retailer Software Subscription)</h2>
      <p><em>Note: This is strictly for the retailer software subscription, NOT for customer orders.</em></p>
      
      {billingStatus ? (
        <div>
          <p>Current Plan: <strong>{billingStatus.plan}</strong></p>
          <p>Last Updated: {new Date(billingStatus.updated_at).toLocaleString()}</p>
        </div>
      ) : (
        <p>Loading status...</p>
      )}

      <button onClick={handleTestCheckout}>Test Checkout</button>
    </div>
  );
}
