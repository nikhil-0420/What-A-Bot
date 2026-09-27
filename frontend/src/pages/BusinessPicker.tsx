import { useState } from 'react';
import type { Business } from '../api/client';
import AlertBanner from '../components/AlertBanner';
import Header from '../components/Header';
import '../components/portal.css';

type BusinessPickerProps = {
  businesses: Business[];
  loading?: boolean;
  error?: string;
  onSelect: (business: Business) => void;
  onLogout: () => void;
  onRetry?: () => void;
  ownerEmail?: string;
};

export default function BusinessPicker({
  businesses,
  loading = false,
  error,
  onSelect,
  onLogout,
  onRetry,
  ownerEmail,
}: BusinessPickerProps) {
  const [selectedBusiness, setSelectedBusiness] = useState<Business | null>(null);

  return (
    <main className="picker-page">
      <Header email={ownerEmail} onLogout={onLogout} />

      <section className="picker-content">
        <p className="eyebrow">OWNER WORKSPACE <span> / </span> BUSINESS ACCESS</p>
        <h1>Choose your shop</h1>
        <p className="picker-intro">You can access only businesses connected to your owner account.</p>

        {error && (
          <AlertBanner
            title="Could not load businesses"
            message={error}
            onRetry={onRetry}
          />
        )}
        {loading ? (
          <div className="loading-state" role="status"><span className="button-spinner" />Loading your businesses</div>
        ) : businesses.length > 0 ? (
          <div className="business-list" aria-label="Your businesses">
            {businesses.map((business) => (
              <button
                className={`business-row${selectedBusiness?.business_id === business.business_id ? ' is-selected' : ''}`}
                key={business.business_id}
                onClick={() => setSelectedBusiness(business)}
                type="button"
                aria-pressed={selectedBusiness?.business_id === business.business_id}
              >
                <span className="business-icon" aria-hidden="true">
                  {business.name.trim().charAt(0).toUpperCase() || 'S'}
                </span>
                <span className="business-info">
                  <strong>{business.name}</strong>
                  <span className="business-kind">{business.business_type.replaceAll('_', ' ')}</span>
                  <span className="business-id">ID: {business.business_id}</span>
                </span>
                <span className="business-open">
                  {selectedBusiness?.business_id === business.business_id ? 'Selected' : 'Select shop'}
                  <span aria-hidden="true">&#8594;</span>
                </span>
              </button>
            ))}
          </div>
        ) : error ? null : (
          <div className="empty-state">
            <span className="empty-mark" aria-hidden="true">&#8212;</span>
            <h2>No businesses connected</h2>
            <p>This owner account does not currently have access to a business.</p>
            <button className="button button-secondary" type="button" onClick={onLogout}>Sign out</button>
          </div>
        )}

        {selectedBusiness && (
          <div className="business-confirmation" role="status">
            <div>
              <span className="business-confirmation__label">READY TO OPEN</span>
              <strong>{selectedBusiness.name}</strong>
            </div>
            <div className="business-confirmation__actions">
              <button className="text-button" type="button" onClick={() => setSelectedBusiness(null)}>Cancel</button>
              <button className="button button-primary" type="button" onClick={() => onSelect(selectedBusiness)}>
                Open shop <span aria-hidden="true">&#8594;</span>
              </button>
            </div>
          </div>
        )}
        <p className="picker-footnote">Business access is verified by the server on every request.</p>
      </section>
    </main>
  );
}
