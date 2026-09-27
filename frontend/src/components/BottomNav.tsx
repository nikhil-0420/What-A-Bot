import './portal.css';

export type TabType = 'overview' | 'orders' | 'catalog' | 'bot-setup' | 'stock' | 'holds' | 'evidence' | 'billing';

type BottomNavProps = {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  availableTabs?: TabType[];
};

const tabs: { id: TabType; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: 'dashboard' },
  { id: 'orders', label: 'Orders', icon: 'receipt_long' },
  { id: 'catalog', label: 'Catalog', icon: 'inventory_2' },
  { id: 'bot-setup', label: 'Bot Setup', icon: 'tune' },
];

export function BottomNav({ activeTab, onTabChange, availableTabs }: BottomNavProps) {
  const visibleTabs = availableTabs ? tabs.filter((tab) => availableTabs.includes(tab.id)) : tabs;

  return (
    <nav className="portal-bottom-nav" aria-label="Shop navigation">
      {visibleTabs.map((tab) => (
        <button
          key={tab.id}
          className={`portal-bottom-nav__item${activeTab === tab.id ? ' is-active' : ''}`}
          type="button"
          aria-current={activeTab === tab.id ? 'page' : undefined}
          onClick={() => onTabChange(tab.id)}
        >
          <span className="material-symbols-outlined portal-bottom-nav__icon" aria-hidden="true">
            {tab.icon}
          </span>
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}

export default BottomNav;