// client.ts - API wrappers based on CONTRACTS.md
const RAW_BASE_URL = (import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '').trim();
const BASE_URL = RAW_BASE_URL ? RAW_BASE_URL.replace(/\/$/, '') : '';
const TOKEN_KEY = 'emberground.owner-token';
const OWNER_EMAIL_KEY = 'emberground.owner-email';

export type BusinessType = 'retail' | 'service';

export interface OwnerProfile {
  owner_id: string;
  email: string;
  businesses: string[];
}

export type Owner = OwnerProfile;

export interface BusinessSummary {
  business_id: string;
  name: string;
  business_type: BusinessType;
  status?: string;
  bot_status_label?: string;
  skus_mapped?: number;
}

export type Business = BusinessSummary;

export interface BotLinkResponse {
  token: string;
  deep_link_url: string;
  expires_at: string;
}

export type BotLink = BotLinkResponse;

export interface CatalogItem {
  sku: string;
  name: string;
  brand: string;
  ruling: 'ruled' | 'unruled';
  size: 'A4' | 'A5';
  price_paise: number;
  qty: number;
}

export interface ServiceItem {
  service_id: string;
  name: string;
  duration_minutes: number;
  price_paise: number;
}

export interface ServiceSlot {
  slot_id: string;
  starts_at: string;
  capacity: number;
}

export interface OrderItem {
  order_id: string;
  status: 'draft' | 'held' | 'confirmed' | 'cancelled';
  total_paise: number;
  created_at?: string;
}

export interface EvidenceRecord {
  [field: string]: unknown;
  event_id?: string;
  input_id?: string;
  kind?: string;
  data?: Record<string, unknown>;
  created_at?: string;
}

export interface BillingStatus {
  plan: string;
  updated_at: string;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
  };
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) || localStorage.getItem('token');
}

export function setAuthToken(token: string, email?: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem('token', token);
  if (email) localStorage.setItem(OWNER_EMAIL_KEY, email);
}

export function clearAuthToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem('token');
  localStorage.removeItem(OWNER_EMAIL_KEY);
}

export function getSavedEmail(): string {
  return localStorage.getItem(OWNER_EMAIL_KEY) || '';
}

function handleDevMock<T>(endpoint: string, _options: RequestInit = {}): T {
  if (endpoint === '/auth/login' || endpoint === '/auth/register') {
    return { token: `dev_token_${Date.now()}` } as T;
  }

  if (endpoint === '/auth/me') {
    const email = getSavedEmail() || 'owner@demo.com';
    return {
      owner_id: '00000000-0000-0000-0000-000000000001',
      email,
      businesses: email.includes('restricted')
        ? ['demo-stationery-1']
        : ['demo-stationery-1', 'demo-supermarket-1', 'demo-services-1'],
    } as T;
  }

  if (endpoint === '/businesses') {
    const email = getSavedEmail();
    const all: BusinessSummary[] = [
      {
        business_id: 'demo-stationery-1',
        name: 'Sharma Stationery',
        business_type: 'retail',
        status: 'active',
        bot_status_label: 'Telegram Bot Active',
        skus_mapped: 50,
      },
      {
        business_id: 'demo-supermarket-1',
        name: 'Daily Fresh Supermarket',
        business_type: 'retail',
        status: 'active',
        bot_status_label: 'Telegram Bot Active',
        skus_mapped: 40,
      },
      {
        business_id: 'demo-services-1',
        name: 'UrbanFix Home Services',
        business_type: 'service',
        status: 'active',
        bot_status_label: 'Live Bot',
        skus_mapped: 12,
      },
    ];
    if (email && email.includes('restricted')) {
      return [all[0]] as T;
    }
    return all as T;
  }

  if (endpoint.includes('/bot-link')) {
    const rand = Math.random().toString(36).slice(2, 10);
    return {
      token: `auth_tok_${rand}`,
      deep_link_url: `https://t.me/WhatABotRetail_bot?start=auth_tok_${rand}`,
      expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    } as T;
  }

  if (endpoint.includes('/catalog')) {
    return [
      { sku: 'A', name: 'Classic Ruled A5', brand: 'Classmate', ruling: 'ruled', size: 'A5', price_paise: 4000, qty: 50 },
      { sku: 'B', name: 'Premium Ruled A5', brand: 'Navneet', ruling: 'ruled', size: 'A5', price_paise: 5000, qty: 40 },
      { sku: 'C', name: 'Deluxe Ruled A5', brand: 'Sundaram', ruling: 'ruled', size: 'A5', price_paise: 6000, qty: 50 },
      { sku: 'D', name: 'Basic Unruled A5', brand: 'Classmate', ruling: 'unruled', size: 'A5', price_paise: 2500, qty: 30 },
    ] as T;
  }

  if (endpoint.includes('/services')) {
    return [
      { service_id: 'srv-ac-repair', name: 'AC Repair & Service', duration_minutes: 60, price_paise: 49900 },
      { service_id: 'srv-plumbing', name: 'Plumbing Inspection & Fix', duration_minutes: 45, price_paise: 29900 },
    ] as T;
  }

  if (endpoint.includes('/holds') || endpoint.includes('/orders')) {
    return [
      { order_id: 'ord_101', status: 'held', total_paise: 125000, created_at: new Date().toISOString() },
      { order_id: 'ord_102', status: 'confirmed', total_paise: 45000, created_at: new Date().toISOString() },
    ] as T;
  }

  if (endpoint.includes('/evidence')) {
    return [
      { event_id: 'ev_1', input_id: 'in_1', kind: 'tool_call', data: { tool: 'find_options', latency_ms: 120 } },
    ] as T;
  }

  if (endpoint.includes('/billing/status')) {
    return { plan: 'trial', updated_at: new Date().toISOString() } as T;
  }

  if (endpoint.includes('/billing/checkout')) {
    return { checkout_url: 'https://test.dodopayments.com/buy/mock_session' } as T;
  }

  return {} as T;
}

export async function fetchWithAuth<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const token = getAuthToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const targetUrl = `${BASE_URL}${endpoint}`;
  let response: Response;
  try {
    response = await fetch(targetUrl, { ...options, headers });
  } catch (err: any) {
    if (import.meta.env.DEV) {
      console.warn(`[DEV MODE] Backend unreachable at ${targetUrl}. Using mock fallback.`, err);
      return handleDevMock<T>(endpoint, options);
    }
    const errDetail = err?.message ? ` (${err.message})` : '';
    throw new ApiError(`Could not reach the server${errDetail}. Target: ${targetUrl || window.location.origin + endpoint}`, 0);
  }

  const rawText = await response.text().catch(() => '');
  let payload: any = null;
  try {
    payload = rawText ? JSON.parse(rawText) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearAuthToken();
      if (typeof window !== 'undefined' && window.location.hash) {
        window.location.hash = 'login';
      }
    }
    const serverMessage =
      (payload && typeof payload.detail === 'string' && payload.detail) ||
      (payload && typeof payload.error === 'object' && payload.error?.message) ||
      (payload && typeof payload.message === 'string' && payload.message) ||
      (payload && typeof payload.detail === 'object' && JSON.stringify(payload.detail)) ||
      rawText ||
      `Request failed with status ${response.status}.`;

    throw new ApiError(
      serverMessage,
      response.status,
      payload?.error?.code,
    );
  }

  return (payload !== null ? payload : (rawText as unknown)) as T;
}

const businessPath = (id: string) => `/businesses/${encodeURIComponent(id)}`;

export const api = {
  login: (data: { email: string; password: string }) =>
    fetchWithAuth<{ token: string }>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  register: (data: { email: string; password: string }) =>
    fetchWithAuth<{ token: string; status?: string }>('/auth/register', { method: 'POST', body: JSON.stringify(data) }),
  getMe: () => fetchWithAuth<Owner>('/auth/me'),
  getBusinesses: () => fetchWithAuth<Business[]>('/businesses'),
  createBotLink: (id: string) => fetchWithAuth<BotLink>(`${businessPath(id)}/bot-link`, { method: 'POST' }),
  getCatalog: (id: string) => fetchWithAuth<CatalogItem[]>(`${businessPath(id)}/catalog`),
  addItem: (id: string, data: Record<string, unknown>) =>
    fetchWithAuth<CatalogItem>(`${businessPath(id)}/catalog`, { method: 'POST', body: JSON.stringify(data) }),
  getServices: (id: string) => fetchWithAuth<ServiceItem[]>(`${businessPath(id)}/services`),
  getSlots: (id: string, serviceId?: string) => {
    const query = serviceId ? `?${new URLSearchParams({ service_id: serviceId })}` : '';
    return fetchWithAuth<ServiceSlot[]>(`${businessPath(id)}/slots${query}`);
  },
  getOrders: (id: string, status?: string) => {
    const query = status ? `?${new URLSearchParams({ status })}` : '';
    return fetchWithAuth<OrderItem[]>(`${businessPath(id)}/orders${query}`);
  },
  getHolds: (id: string) => fetchWithAuth<OrderItem[]>(`${businessPath(id)}/holds`),
  resolveHold: (id: string, data: { order_id: string; approve: boolean }) =>
    fetchWithAuth<OrderItem>(`${businessPath(id)}/holds`, { method: 'POST', body: JSON.stringify(data) }),
  getEvidence: (id: string) => fetchWithAuth<EvidenceRecord[]>(`${businessPath(id)}/evidence`),
  createCheckout: (id: string) =>
    fetchWithAuth<{ checkout_url: string }>(`${businessPath(id)}/billing/checkout`, { method: 'POST' }),
  getBillingStatus: (id: string) =>
    fetchWithAuth<BillingStatus>(`${businessPath(id)}/billing/status`),
};

class ApiClient {
  private simulate429 = false;

  isSimulate429() {
    return this.simulate429;
  }

  setSimulate429(val: boolean) {
    this.simulate429 = val;
  }

  setToken(token: string | null, email?: string) {
    if (token) setAuthToken(token, email);
    else clearAuthToken();
  }

  getToken() {
    return getAuthToken();
  }

  getSavedEmail() {
    return getSavedEmail();
  }

  isAuthenticated() {
    return Boolean(getAuthToken());
  }

  async login(email: string, password: string) {
    const result = await api.login({ email, password });
    setAuthToken(result.token, email);
    return result;
  }

  register(email: string, password: string) {
    return api.register({ email, password });
  }

  getMe() {
    return api.getMe();
  }

  getBusinesses() {
    return api.getBusinesses();
  }

  createBotLink(businessId: string) {
    return api.createBotLink(businessId);
  }

  getCatalog(businessId: string) {
    return api.getCatalog(businessId);
  }

  addItem(businessId: string, data: Record<string, unknown>) {
    return api.addItem(businessId, data);
  }

  getServices(businessId: string) {
    return api.getServices(businessId);
  }

  getSlots(businessId: string, serviceId?: string) {
    return api.getSlots(businessId, serviceId);
  }

  getOrders(businessId: string, status?: string) {
    return api.getOrders(businessId, status);
  }

  getHolds(businessId: string) {
    return api.getHolds(businessId);
  }

  resolveHold(businessId: string, orderId: string, approve: boolean) {
    return api.resolveHold(businessId, { order_id: orderId, approve });
  }

  getEvidence(businessId: string) {
    return api.getEvidence(businessId);
  }

  createBillingCheckout(businessId: string) {
    return api.createCheckout(businessId);
  }

  getBillingStatus(businessId: string) {
    return api.getBillingStatus(businessId);
  }
}

export const apiClient = new ApiClient();
export default apiClient;
