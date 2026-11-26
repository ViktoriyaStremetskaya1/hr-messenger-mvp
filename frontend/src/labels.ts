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
