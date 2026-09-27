import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Stock({ businessId }: { businessId: string }) {
  const [catalog, setCatalog] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  
  const [formData, setFormData] = useState({
    sku: '',
    name: '',
    brand: '',
    price_paise: '',
    qty: ''
  });

  useEffect(() => {
    api.getCatalog(businessId).then(setCatalog).catch(console.error);
  }, [businessId]);

  const handleAddItem = async (e: React.FormEvent) => {
    e.preventDefault();
    const newItem = {
      sku: formData.sku || 'NEW-' + Math.floor(Math.random() * 1000),
      name: formData.name,
      brand: formData.brand,
      price_paise: parseInt(formData.price_paise, 10) * 100 || 0,
      qty: parseInt(formData.qty, 10) || 0
    };
    try {
      await api.addItem(businessId, newItem);
      setCatalog(prev => [...prev, newItem]);
      setShowForm(false);
      setFormData({ sku: '', name: '', brand: '', price_paise: '', qty: '' });
    } catch (e) {
      alert("Failed to add item");
    }
  };

  return (
    <div className="glass-panel">
      <div className="content-header">
        <h2>Stock Management</h2>
        <button onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Add Item'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleAddItem} style={{ display: 'grid', gap: '12px', background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '8px', marginBottom: '16px' }}>
          <h3>Add New Product</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <input placeholder="SKU (e.g. BOOK-1)" value={formData.sku} onChange={e => setFormData({...formData, sku: e.target.value})} required />
            <input placeholder="Product Name" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} required />
            <input placeholder="Brand" value={formData.brand} onChange={e => setFormData({...formData, brand: e.target.value})} required />
            <input placeholder="Price (₹)" type="number" step="0.01" value={formData.price_paise} onChange={e => setFormData({...formData, price_paise: e.target.value})} required />
            <input placeholder="Initial Quantity" type="number" value={formData.qty} onChange={e => setFormData({...formData, qty: e.target.value})} required />
          </div>
          <button type="submit" style={{ width: 'fit-content' }}>Save Item</button>
        </form>
      )}

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
              <td>₹{(c.price_paise / 100).toFixed(2)}</td>
              <td><span className={c.qty > 5 ? 'badge success' : 'badge pending'}>{c.qty} in stock</span></td>
              <td><button style={{ padding: '6px 12px', fontSize: '12px' }}>Adjust</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
