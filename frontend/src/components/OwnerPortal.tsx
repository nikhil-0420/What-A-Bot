import { useEffect, useState } from 'react';
import { ApiError, api, clearAuthToken, getAuthToken } from '../api/client';
import type { Business, Owner } from '../api/client';
import AlertBanner from './AlertBanner';
import BottomNav from './BottomNav';
import type { TabType } from './BottomNav';
import BotLink from '../pages/BotLink';
import BusinessPicker from '../pages/BusinessPicker';
import Login from '../pages/Login';
import Navbar from './Navbar';
import './portal.css';

type PortalState = 'loading' | 'signed-out' | 'businesses' | 'shop';
const ownerTabs: TabType[] = ['overview', 'bot-setup'];

export default function OwnerPortal() {
  const [portalState, setPortalState] = useState<PortalState>(getAuthToken() ? 'loading' : 'signed-out');
  const [owner, setOwner] = useState<Owner | null>(null);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [business, setBusiness] = useState<Business | null>(null);
  const [showBotLink, setShowBotLink] = useState(false);
  const [error, setError] = useState('');

  async function fetchOwnerWorkspace() {
    try {
      const [ownerData, businessData] = await Promise.all([api.getMe(), api.getBusinesses()]);
      setOwner(ownerData);
      setBusinesses(businessData);
      setPortalState('businesses');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        clearAuthToken();
        setPortalState('signed-out');
        setError('Your session has expired. Please sign in again.');
      } else {
        setPortalState('businesses');
        setError(cause instanceof ApiError ? cause.message : 'Could not load your owner workspace.');
      }
    }
  }

  function loadOwnerWorkspace() {
    setPortalState('loading');
    setError('');
    void fetchOwnerWorkspace();
  }

  useEffect(() => {
    if (!getAuthToken()) return;

    let active = true;
    void Promise.all([api.getMe(), api.getBusinesses()])
      .then(([ownerData, businessData]) => {
        if (!active) return;
        setOwner(ownerData);
        setBusinesses(businessData);
        setPortalState('businesses');
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) {
          clearAuthToken();
          setPortalState('signed-out');
          setError('Your session has expired. Please sign in again.');
        } else {
          setPortalState('businesses');
          setError(cause instanceof ApiError ? cause.message : 'Could not load your owner workspace.');
        }
      });

    return () => {
      active = false;
    };
  }, []);

  function signOut() {
    clearAuthToken();
    setOwner(null);
    setBusinesses([]);
    setBusiness(null);
    setShowBotLink(false);
    setError('');
    setPortalState('signed-out');
  }

  if (portalState === 'loading') {
    return <main className="portal-loading"><span className="button-spinner" />Opening your owner workspace</main>;
  }

  if (portalState === 'signed-out') {
    return <Login onLogin={loadOwnerWorkspace} />;
  }

  if (!business || portalState === 'businesses') {
    return (
      <BusinessPicker
        businesses={businesses}
        error={error}
        ownerEmail={owner?.email}
        onRetry={loadOwnerWorkspace}
        onSelect={(selected) => {
          setBusiness(selected);
          setShowBotLink(false);
          setPortalState('shop');
          setError('');
        }}
        onLogout={signOut}
      />
    );
  }

  return (
    <div className="portal-workspace">
      {!showBotLink && (
        <Navbar
          business={business}
          onChangeBusiness={() => {
            setBusiness(null);
            setShowBotLink(false);
            setPortalState('businesses');
          }}
          onCreateBotLink={() => setShowBotLink(true)}
          onLogout={signOut}
        />
      )}
      {showBotLink ? (
        <BotLink business={business} onBack={() => setShowBotLink(false)} />
      ) : (
        <main className="shop-welcome">
          <p className="eyebrow">OWNER WORKSPACE <span> / </span> {business.business_type.toUpperCase()}</p>
          <div className="welcome-heading">
            <div>
              <h1>{business.name}</h1>
              <p>Business access is active for <strong>{owner?.email}</strong>.</p>
            </div>
            <button className="button button-primary" type="button" onClick={() => setShowBotLink(true)}>Connect WhatsApp <span aria-hidden="true">&#8594;</span></button>
          </div>
          {error && (
            <AlertBanner
              title="Workspace notice"
              message={error}
              onDismiss={() => setError('')}
            />
          )}
          <div className="welcome-rule" />
          <p className="welcome-note">Choose “Connect WhatsApp” to create a secure, single-use setup link for this shop.</p>
        </main>
      )}
      <BottomNav
        activeTab={showBotLink ? 'bot-setup' : 'overview'}
        availableTabs={ownerTabs}
        onTabChange={(tab) => setShowBotLink(tab === 'bot-setup')}
      />
    </div>
  );
}