import type { AppStatus, Role, Screening } from './api';

export const STATUS: Record<AppStatus, { label: string; color: string }> = {
  new: { label: 'Новый', color: 'gray' },
  in_campaign: { label: 'В рассылке', color: 'blue' },
  replied: { label: 'Ответил', color: 'cyan' },
  booked: { label: 'Записан на интервью', color: 'violet' },
  attended: { label: 'Пришёл', color: 'teal' },
  no_show: { label: 'Не пришёл', color: 'red' },
  offer: { label: 'Оффер', color: 'orange' },
  hired: { label: 'Вышел', color: 'green' },
};

export const SCREENING: Record<Screening, { label: string; color: string }> = {
  fit: { label: 'Подходит', color: 'green' },
  unfit: { label: 'Не подходит', color: 'red' },
  review: { label: 'На ревью', color: 'yellow' },
};

export const ROLES: Record<Role, string> = { admin: 'Администратор', lead: 'Руководитель', recruiter: 'Рекрутер' };

export const statusOptions = Object.entries(STATUS).map(([value, v]) => ({ value, label: v.label }));
export const screeningOptions = Object.entries(SCREENING).map(([value, v]) => ({ value, label: v.label }));
export const roleOptions = Object.entries(ROLES).map(([value, label]) => ({ value, label }));

export const TAG_COLORS = ['gray', 'red', 'orange', 'yellow', 'green', 'teal', 'cyan', 'blue', 'violet', 'pink'];

export function money(from: number | null, to: number | null): string {
  const f = (n: number) => n.toLocaleString('ru-RU');
  if (from && to) return `${f(from)} – ${f(to)} ₸`;
  if (from) return `от ${f(from)} ₸`;
  if (to) return `до ${f(to)} ₸`;
  return '—';
}

export function dt(s: string | null | undefined): string {
  return s ? new Date(s).toLocaleString('ru-RU', { timeZone: 'Asia/Almaty', dateStyle: 'short', timeStyle: 'short' }) : '—';
}

export const INTERVIEW_STATUS: Record<string, { label: string; color: string }> = {
  booked: { label: 'Записан', color: 'violet' }, attended: { label: 'Пришёл', color: 'teal' }, no_show: { label: 'Не пришёл', color: 'red' },
  cancelled: { label: 'Отменено', color: 'gray' }, rescheduled: { label: 'Перенесено', color: 'gray' },
};

const TZ = 'Asia/Almaty';
export const time = (s: string) => new Date(s).toLocaleTimeString('ru-RU', { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
export const dayLabel = (s: string) => {
  const t = new Date(s).toLocaleDateString('ru-RU', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' });
  return t.charAt(0).toUpperCase() + t.slice(1);
};
export const dayKey = (s: string) => new Date(s).toLocaleDateString('sv-SE', { timeZone: TZ });
export const todayKey = () => new Date().toLocaleDateString('sv-SE', { timeZone: TZ });
