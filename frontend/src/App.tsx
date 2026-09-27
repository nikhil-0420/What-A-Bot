import { useState, useEffect } from 'react'
import Login from './pages/Login'
import Register from './pages/Register'
import BusinessPicker from './pages/BusinessPicker'
import BotLink from './pages/BotLink'
import Stock from './pages/Stock'
import Holds from './pages/Holds'
import Evidence from './pages/Evidence'
import Billing from './pages/Billing'
import './App.css'
import './index.css'

function App() {
  const [route, setRoute] = useState(window.location.hash.slice(1) || 'login');

  useEffect(() => {
    const handleHashChange = () => {
      setRoute(window.location.hash.slice(1) || 'login');
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const navigate = (newRoute: string) => {
    window.location.hash = newRoute;
  };

  // Extract business ID from routes like "dashboard/demo-stationery-1"
  const isDashboard = route.startsWith('dashboard/');
  const businessId = isDashboard ? route.split('/')[1] : null;

  return (
    <div className="app-container">
      <aside className="app-sidebar">
        <div className="sidebar-header">
          <h1>What-A-Bot</h1>
          <span className="version-badge">APP</span>
        </div>
        
        <nav className="app-nav">
          {!businessId ? (
            <>
              <div className="nav-group-title">ACCOUNT</div>
              <button className={route === 'login' ? 'active' : ''} onClick={() => navigate('login')}>Login</button>
              <button className={route === 'register' ? 'active' : ''} onClick={() => navigate('register')}>Register</button>
              <button className={route === 'businesses' ? 'active' : ''} onClick={() => navigate('businesses')}>My Businesses</button>
            </>
          ) : (
            <>
              <div className="nav-group-title">STORE DASHBOARD</div>
              <button className={route === `dashboard/${businessId}` ? 'active' : ''} onClick={() => navigate(`dashboard/${businessId}`)}>Stock & Catalog</button>
              <button className={route === `dashboard/${businessId}/holds` ? 'active' : ''} onClick={() => navigate(`dashboard/${businessId}/holds`)}>Order Holds</button>
              <button className={route === `dashboard/${businessId}/evidence` ? 'active' : ''} onClick={() => navigate(`dashboard/${businessId}/evidence`)}>AI Evidence</button>
              
              <div className="nav-group-title" style={{ marginTop: '24px' }}>SETTINGS</div>
              <button className={route === `dashboard/${businessId}/billing` ? 'active' : ''} onClick={() => navigate(`dashboard/${businessId}/billing`)}>Billing Plan</button>
              <button className={route === `dashboard/${businessId}/link` ? 'active' : ''} onClick={() => navigate(`dashboard/${businessId}/link`)}>Telegram Bot Link</button>
              
              <div style={{ marginTop: 'auto', paddingTop: '24px' }}>
                <button style={{ width: '100%', opacity: 0.7 }} onClick={() => { localStorage.removeItem('token'); navigate('login'); }}>Logout</button>
              </div>
            </>
          )}
        </nav>
      </aside>

      <main className="app-content">
        <div className="content-inner">
          {route === 'login' && <Login navigate={navigate} />}
          {route === 'register' && <Register navigate={navigate} />}
          {route === 'businesses' && <BusinessPicker navigate={navigate} />}
          {businessId && route === `dashboard/${businessId}` && <Stock businessId={businessId} />}
          {businessId && route === `dashboard/${businessId}/holds` && <Holds businessId={businessId} />}
          {businessId && route === `dashboard/${businessId}/evidence` && <Evidence businessId={businessId} />}
          {businessId && route === `dashboard/${businessId}/billing` && <Billing businessId={businessId} />}
          {businessId && route === `dashboard/${businessId}/link` && <BotLink businessId={businessId} />}
        </div>
      </main>
    </div>
  )
}

export default App
