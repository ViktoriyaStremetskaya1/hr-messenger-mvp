export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
      .join('; ');
  }
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: string }).message);
  return fallback;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    headers: json !== undefined ? { 'Content-Type': 'application/json', ...headers } : headers,
    body: json !== undefined ? JSON.stringify(json) : init.body,
    ...rest,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    throw new ApiError(res.status, messageFrom(detail, `Ошибка ${res.status}`), detail);
  }
  return data as T;
}

export function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

// ---- Типы ----
export type Role = 'admin' | 'lead' | 'recruiter';
export type AppStatus = 'new' | 'in_campaign' | 'replied' | 'booked' | 'attended' | 'no_show' | 'offer' | 'hired';
export type Screening = 'fit' | 'unfit' | 'review';

export interface User {
  id: number;
  login: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
}
export interface Tag {
  id: number;
  name: string;
  color: string;
}
export interface FaqItem {
  q: string;
  a: string;
}
export interface Vacancy {
  id: number;
  title: string;
  city: string;
  schedule: string | null;
  salary_from: number | null;
  salary_to: number | null;
  requirements: string | null;
  office_address: string | null;
  description: string | null;
  faq: FaqItem[];
  is_active: boolean;
  candidates_count: number;
}
export interface Application {
  id: number;
  vacancy: { id: number; title: string; city: string };
  status: AppStatus;
  screening_result: Screening | null;
  recruiter_id: number | null;
  updated_at: string;
}
export interface Candidate {
  id: number;
  full_name: string;
  phone_masked: string;
  city: string | null;
  source: string | null;
  desired_position: string | null;
  language: 'ru' | 'kk' | null;
  notes: string | null;
  is_reserve: boolean;
  unsubscribed_at: string | null;
  last_touch_at: string | null;
  owner_id: number | null;
  created_at: string;
  tags: Tag[];
  applications: Application[];
  status: AppStatus;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface AuditEntry {
  id: number;
  user_id: number | null;
  action: string;
  entity: string | null;
  entity_id: string | null;
  diff: Record<string, unknown>;
  ip: string | null;
  created_at: string;
}
