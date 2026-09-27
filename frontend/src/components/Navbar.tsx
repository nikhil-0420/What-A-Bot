import type { Business } from '../api/client';

type NavbarProps = {
	business: Business;
	onChangeBusiness: () => void;
	onCreateBotLink: () => void;
	onLogout: () => void;
};

export default function Navbar({ business, onChangeBusiness, onCreateBotLink, onLogout }: NavbarProps) {
	return (
		<header className="portal-navbar">
			<a className="brand-lockup" href="/" aria-label="EmberGround home">
				<span className="brand-mark" aria-hidden="true">E</span>
				<span>emberground<span className="brand-period">.</span></span>
			</a>
			<div className="nav-context">
				<span className="nav-caption">CURRENT SHOP</span>
				<strong>{business.name}</strong>
				<span className="nav-type">{business.business_type.replaceAll('_', ' ')}</span>
			</div>
			<nav className="nav-actions" aria-label="Owner actions">
				<button className="text-button" type="button" onClick={onChangeBusiness}>Change shop</button>
				<button className="button button-secondary nav-link-button" type="button" onClick={onCreateBotLink}>Connect Telegram</button>
				<button className="text-button" type="button" onClick={onLogout}>Sign out</button>
			</nav>
		</header>
	);
}
