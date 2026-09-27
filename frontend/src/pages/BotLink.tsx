import { useState } from 'react';
import { api } from '../api/client';

export default function BotLink({ businessId }: { businessId: string }) {
  const [linkData, setLinkData] = useState<any>(null);

  const generateLink = async () => {
    try {
      const data = await api.createBotLink(businessId);
      setLinkData(data);
    } catch (err) {
      alert('Failed to generate bot link');
    }
  };

  return (
    <div className="glass-panel">
      <h2>Bot Link</h2>
      {!linkData ? (
        <button onClick={generateLink}>Generate Bot Deep Link</button>
      ) : (
        <div>
          <p>Click the link below or copy it to bind your Telegram session to this business.</p>
          <p style={{ color: 'var(--success)', fontWeight: 500 }}>
            Important: You MUST click the link and press /start in Telegram for the link to activate!
          </p>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '16px' }}>
            <input type="text" readOnly value={linkData.deep_link_url} />
            <button onClick={() => navigator.clipboard.writeText(linkData.deep_link_url)}>Copy</button>
            <a href={linkData.deep_link_url} target="_blank" rel="noreferrer" style={{ marginLeft: '8px' }}>
              <button style={{ background: 'var(--success)' }}>Open</button>
            </a>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            Expires at: {new Date(linkData.expires_at).toLocaleString()}
          </p>
        </div>
      )}
    </div>
  );
}
