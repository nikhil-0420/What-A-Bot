import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Stock({ businessId }: { businessId: string }) {
  const [catalog, setCatalog] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  
  const [formData, setFormData] = useState({
    sku: '',
    name: '',
    brand: '',
    price_paise: '',
    qty: ''
  });

  useEffect(() => {
    setLoading(true);
    api.getCatalog(businessId)
      .then(setCatalog)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [businessId]);

  const handleAddItem = async (e: React.FormEvent) => {
    e.preventDefault();
    const newItem = {
      sku: formData.sku || 'NEW-' + Math.floor(Math.random() * 1000),
      name: formData.name,
      brand: formData.brand,
      price_paise: Math.round(parseFloat(formData.price_paise || '0') * 100),
      qty: parseInt(formData.qty, 10) || 0
    };
    try {
      await api.addItem(businessId, newItem);
      setCatalog(prev => [...prev, newItem]);
      setShowForm(false);
      setFormData({ sku: '', name: '', brand: '', price_paise: '', qty: '' });
    } catch {
      alert("Failed to add item");
    }
  };

  return (
    <div className="glass-panel">
      <div className="content-header">
        <div>
          <h2>Stock & Catalog</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
            Real-time inventory and product catalog management.
          </p>
        </div>
        <button
          className={showForm ? 'button-secondary' : 'button-primary'}
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? 'Cancel' : '+ Add Item'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleAddItem}
          style={{
            display: 'grid',
            gap: '14px',
            background: 'var(--bg-subtle)',
            padding: '20px',
            borderRadius: '10px',
            border: '1px solid var(--border-color)',
            marginBottom: '20px'
          }}
        >
          <h3 style={{ margin: 0 }}>Add New Product</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <input placeholder="SKU (e.g. BOOK-1)" value={formData.sku} onChange={e => setFormData({...formData, sku: e.target.value})} required />
            <input placeholder="Product Name" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} required />
            <input placeholder="Brand" value={formData.brand} onChange={e => setFormData({...formData, brand: e.target.value})} required />
            <input placeholder="Price (₹)" type="number" step="0.01" value={formData.price_paise} onChange={e => setFormData({...formData, price_paise: e.target.value})} required />
            <input placeholder="Initial Quantity" type="number" value={formData.qty} onChange={e => setFormData({...formData, qty: e.target.value})} required />
          </div>
          <button type="submit" style={{ width: 'fit-content' }}>Save Item</button>
        </form>
      )}

      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading catalog...
        </div>
      ) : catalog.length === 0 ? (
        <div style={{ padding: '32px', textAlign: 'center', background: 'var(--bg-subtle)', borderRadius: '8px', border: '1px dashed var(--border-color)' }}>
          <p style={{ margin: 0, color: 'var(--text-muted)' }}>No products in catalog yet. Click "+ Add Item" to populate stock.</p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Name</th>
              <th>Brand</th>
              <th>Price</th>
              <th>Qty</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {catalog.map(c => (
              <tr key={c.sku}>
                <td><span className="badge">{c.sku}</span></td>
                <td style={{ fontWeight: 500 }}>{c.name}</td>
                <td style={{ color: 'var(--text-muted)' }}>{c.brand}</td>
                <td>₹{((c.price_paise || 0) / 100).toFixed(2)}</td>
                <td><span className={c.qty > 5 ? 'badge success' : 'badge pending'}>{c.qty} in stock</span></td>
                <td><button className="button-secondary" style={{ padding: '5px 10px', fontSize: '12px' }}>Adjust</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
