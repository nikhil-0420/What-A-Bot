import './portal.css';

type HeaderProps = {
  email?: string;
  title?: string;
  showBack?: boolean;
  onBack?: () => void;
  onLogout?: () => void;
};

export function Header({ email, title, showBack = false, onBack, onLogout }: HeaderProps) {
  if (!showBack && !email && !title) {
    return null;
  }
  return (
    <header className="portal-header">
      <div className="portal-header__inner">
        {showBack ? (
          <div className="portal-header__back-group">
            <button className="portal-header__back" type="button" onClick={onBack} aria-label="Go back">
              <span aria-hidden="true">&#8592;</span>
            </button>
            <div className="portal-header__page-title">
              <span className="brand-mark" aria-hidden="true">E</span>
              <strong>{title || 'Owner workspace'}</strong>
            </div>
          </div>
        ) : (
          <div className="portal-header__brand-group">
            <a className="brand-lockup" href="/" aria-label="EmberGround home">
              <span className="brand-mark" aria-hidden="true">E</span>
              <span>emberground<span className="brand-period">.</span></span>
            </a>
            <span className="portal-header__role">OWNER</span>
          </div>
        )}
        <div className="portal-header__account">
          {email && <span className="portal-header__email">{email}</span>}
          {onLogout && (
            <button className="portal-header__logout" type="button" onClick={onLogout}>
              Sign out
            </button>
          )}
          <span className="portal-header__avatar" aria-hidden="true">{email?.charAt(0).toUpperCase() || 'O'}</span>
        </div>
      </div>
    </header>
  );
}

export default Header;