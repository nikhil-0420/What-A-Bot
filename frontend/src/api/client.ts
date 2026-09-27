const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
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

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string, email?: string) {
  localStorage.setItem(TOKEN_KEY, token);
  if (email) localStorage.setItem(OWNER_EMAIL_KEY, email);
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(OWNER_EMAIL_KEY);
}

export function getSavedEmail() {
  return localStorage.getItem(OWNER_EMAIL_KEY) || '';
}

export async function fetchWithAuth<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const token = getAuthToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${endpoint}`, { ...options, headers });
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.', 0);
  }

  const payload = await response.json().catch(() => null) as ApiErrorEnvelope | null;

  if (!response.ok) {
    throw new ApiError(
      payload?.error?.message || `Request failed (${response.status}). Please try again.`,
      response.status,
      payload?.error?.code,
    );
  }

  return payload as T;
}

const businessPath = (id: string) => `/businesses/${encodeURIComponent(id)}`;

export const api = {
  login: (data: { email: string; password: string }) =>
    fetchWithAuth<{ token: string }>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  getMe: () => fetchWithAuth<Owner>('/auth/me'),
  getBusinesses: () => fetchWithAuth<Business[]>('/businesses'),
  createBotLink: (id: string) => fetchWithAuth<BotLink>(`${businessPath(id)}/bot-link`, { method: 'POST' }),
  getCatalog: (id: string) => fetchWithAuth<CatalogItem[]>(`${businessPath(id)}/catalog`),
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
