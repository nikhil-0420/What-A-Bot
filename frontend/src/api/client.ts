// client.ts - API wrappers based on CONTRACTS.md
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';


export async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    ...options.headers,
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {})
  };
  const res = await fetch(`${BASE_URL}${endpoint}`, { ...options, headers });
  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.hash = 'login';
    }
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  login: (data: any) => fetchWithAuth('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  register: (data: any) => fetchWithAuth('/auth/register', { method: 'POST', body: JSON.stringify(data) }),
  getMe: () => fetchWithAuth('/auth/me'),
  getBusinesses: () => fetchWithAuth('/businesses'),
  createBotLink: (id: string) => fetchWithAuth(`/businesses/${id}/bot-link`, { method: 'POST' }),
  getCatalog: (id: string) => fetchWithAuth(`/businesses/${id}/catalog`),
  addItem: (id: string, data: any) => fetchWithAuth(`/businesses/${id}/catalog`, { method: 'POST', body: JSON.stringify(data) }),
  getServices: (id: string) => fetchWithAuth(`/businesses/${id}/services`),
  getSlots: (id: string, service_id?: string) => fetchWithAuth(`/businesses/${id}/slots${service_id ? `?service_id=${service_id}` : ''}`),
  getOrders: (id: string, status?: string) => fetchWithAuth(`/businesses/${id}/orders${status ? `?status=${status}` : ''}`),
  getHolds: (id: string) => fetchWithAuth(`/businesses/${id}/holds`),
  resolveHold: (id: string, data: any) => fetchWithAuth(`/businesses/${id}/holds`, { method: 'POST', body: JSON.stringify(data) }),
  getEvidence: (id: string) => fetchWithAuth(`/businesses/${id}/evidence`),
  createCheckout: (id: string) => fetchWithAuth(`/businesses/${id}/billing/checkout`, { method: 'POST' }),
  getBillingStatus: (id: string) => fetchWithAuth(`/businesses/${id}/billing/status`)
};
