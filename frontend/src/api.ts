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

export interface Message {
  id: number;
  direction: 'in' | 'out';
  type: string;
  body: string | null;
  payload: { buttons?: { text?: string; title?: string }[]; out?: { buttons?: { title: string }[]; rows?: { title: string }[] } } & Record<string, unknown>;
  status: 'queued' | 'sent' | 'delivered' | 'read' | 'failed' | 'received';
  error: string | null;
  sent_by_user_id: number | null;
  campaign_id: number | null;
  created_at: string;
}
export interface ConversationView {
  scenario: ScenarioState | null;
  conversation: { id: number; mode: 'bot' | 'human'; assignee_id: number | null; unread_count: number } | null;
  messages: Message[];
  window_open: boolean;
  window_expires_at: string | null;
  unsubscribed: boolean;
}
export interface Template {
  id: number;
  name: string;
  language: 'ru' | 'kk';
  category: 'MARKETING' | 'UTILITY';
  status: 'APPROVED' | 'PENDING' | 'REJECTED' | 'LOCAL' | string;
  header: string | null;
  body: string;
  footer: string | null;
  buttons: { type?: string; text?: string }[];
  params_count: number;
}
export interface ChannelStatus {
  mode: 'mock' | 'live';
  configured: boolean;
  display_phone: string;
  api_version: string;
}

export type Texts = string | { ru?: string; kk?: string };
export interface ScenarioOption { id: string; label: { ru?: string; kk?: string }; next: string | null }
export interface ScenarioRule { var: string; op: string; value?: string | number | string[]; next: string | null }
export interface ScenarioNode {
  type: string;
  title?: string;
  text?: Texts;
  next?: string | null;
  template?: string;
  params?: string[];
  options?: ScenarioOption[];
  var?: string;
  timeout_hours?: number | null;
  on_timeout?: string | null;
  expect?: 'text' | 'number';
  rules?: ScenarioRule[];
  else?: string | null;
  screening?: 'fit' | 'unfit' | 'review' | null;
  status?: string | null;
  reserve?: boolean;
  reason?: string;
  empty?: string | null;
}
export interface ScenarioGraph { start: string; nodes: Record<string, ScenarioNode> }
export interface Scenario {
  id: number;
  name: string;
  kind: string;
  description: string | null;
  graph: ScenarioGraph;
  version: number;
  is_active: boolean;
  updated_at: string;
  running: number;
}
export interface LibraryItem { key: string; name: string; kind: string; description: string; graph: ScenarioGraph }
export interface ScenarioState {
  scenario_id: number;
  scenario_name: string;
  current_node: string | null;
  current_title: string | null;
  waiting: boolean;
  outcome: string | null;
  reason: string | null;
  vacancy_id: number | null;
  answers: Record<string, string>;
}

export interface CampaignSegment {
  candidate_ids?: number[];
  cities?: string[];
  vacancy_ids?: number[];
  statuses?: string[];
  screening?: string[];
  is_reserve?: boolean | null;
  tag_ids?: number[];
  languages?: string[];
  sources?: string[];
}
export interface CampaignStats {
  total: number; queued: number; sent: number; skipped: number; skipped_by_reason: Record<string, number>;
  failed: number; delivered: number; read: number; replied: number; screening_fit: number; booked: number; attended: number;
}
export interface Campaign {
  id: number;
  name: string;
  scenario_id: number;
  vacancy_id: number | null;
  segment: CampaignSegment;
  status: 'draft' | 'scheduled' | 'running' | 'paused' | 'done' | 'cancelled';
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_at: string;
  stats: Partial<CampaignStats>;
}
export interface CampaignRecipient {
  id: number;
  candidate_id: number;
  candidate_name: string;
  status: 'queued' | 'sent' | 'skipped' | 'failed';
  skip_reason: string | null;
  error: string | null;
  message_status: string | null;
  processed_at: string | null;
}
export interface SegmentPreview {
  total: number; eligible: number; excluded: Record<string, number>; sample: string[];
}

export interface SlotBooking { interview_id: number; candidate_id: number; candidate_name: string; status: string; confirmed_at: string | null }
export interface Slot {
  id: number; recruiter_id: number; recruiter_name: string; vacancy_id: number | null; vacancy_title: string | null;
  starts_at: string; ends_at: string; capacity: number; office_address: string | null; is_active: boolean; booked: number;
  bookings: SlotBooking[];
}
export interface Interview {
  id: number; slot_id: number; candidate_id: number; candidate_name: string; starts_at: string; ends_at: string; address: string;
  recruiter_name: string; vacancy_title: string | null; status: 'booked' | 'attended' | 'no_show' | 'cancelled' | 'rescheduled';
  booked_via: string; confirmed_at: string | null; reminded_24h_at: string | null; reminded_2h_at: string | null;
}
