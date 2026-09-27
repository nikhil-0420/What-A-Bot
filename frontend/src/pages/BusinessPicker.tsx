import { useEffect, useState } from 'react';
import type { Business } from '../api/client';
import { api, clearAuthToken } from '../api/client';
import AlertBanner from '../components/AlertBanner';
import Header from '../components/Header';
import '../components/portal.css';

type BusinessPickerProps = {
  businesses?: Business[];
  loading?: boolean;
  error?: string;
  onSelect?: (business: Business) => void;
  onLogout?: () => void;
  onRetry?: () => void;
  ownerEmail?: string;
  navigate?: (route: string) => void;
};

export default function BusinessPicker({
  businesses: propBusinesses,
  loading: propLoading = false,
  error: propError,
  onSelect,
  onLogout,
  onRetry,
  ownerEmail,
  navigate,
}: BusinessPickerProps) {
  const [internalBusinesses, setInternalBusinesses] = useState<Business[]>([]);
  const [internalLoading, setInternalLoading] = useState<boolean>(propBusinesses === undefined);
  const [internalError, setInternalError] = useState<string>('');
  const [selectedBusiness, setSelectedBusiness] = useState<Business | null>(null);

  const businesses = propBusinesses ?? internalBusinesses;
  const loading = propBusinesses !== undefined ? propLoading : internalLoading;
  const error = propError ?? internalError;

  const fetchBusinesses = () => {
    setInternalLoading(true);
    setInternalError('');
    api.getBusinesses()
      .then((data) => {
        setInternalBusinesses(data);
      })
      .catch((err) => {
        setInternalError(err instanceof Error ? err.message : 'Failed to load businesses');
      })
      .finally(() => {
        setInternalLoading(false);
      });
  };

  useEffect(() => {
    if (propBusinesses === undefined) {
      let active = true;
      api.getBusinesses()
        .then((data) => {
          if (active) {
            setInternalBusinesses(data);
            setInternalLoading(false);
          }
        })
        .catch((err) => {
          if (active) {
            setInternalError(err instanceof Error ? err.message : 'Failed to load businesses');
            setInternalLoading(false);
          }
        });
      return () => {
        active = false;
      };
    }
  }, [propBusinesses]);

  const handleOpenBusiness = (b: Business) => {
    if (onSelect) {
      onSelect(b);
    }
    if (navigate) {
      navigate(`dashboard/${b.business_id}`);
    }
  };

  const handleLogout = () => {
    if (onLogout) {
      onLogout();
    } else {
      clearAuthToken();
      if (navigate) {
        navigate('login');
      } else {
        window.location.hash = 'login';
      }
    }
  };

  const handleRetry = () => {
    if (onRetry) {
      onRetry();
    } else {
      fetchBusinesses();
    }
  };

  return (
    <main className="picker-page">
      <Header email={ownerEmail} onLogout={handleLogout} />

      <section className="picker-content">
        <p className="eyebrow">OWNER WORKSPACE <span> / </span> BUSINESS ACCESS</p>
        <h1>Choose your shop</h1>
        <p className="picker-intro">You can access only businesses connected to your owner account.</p>

        {error && (
          <AlertBanner
            title="Could not load businesses"
            message={error}
            onRetry={handleRetry}
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
                onClick={() => {
                  if (selectedBusiness?.business_id === business.business_id) {
                    handleOpenBusiness(business);
                  } else {
                    setSelectedBusiness(business);
                  }
                }}
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
                  {selectedBusiness?.business_id === business.business_id ? 'Open shop' : 'Select shop'}
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
            <button className="button button-secondary" type="button" onClick={handleLogout}>Sign out</button>
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
              <button className="button button-primary" type="button" onClick={() => handleOpenBusiness(selectedBusiness)}>
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
