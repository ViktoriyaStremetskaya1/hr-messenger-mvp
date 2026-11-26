import { notifications } from '@mantine/notifications';
import { useQuery } from '@tanstack/react-query';

import { api, type Tag, type User, type Vacancy } from './api';

export const useVacancies = () => useQuery({ queryKey: ['vacancies'], queryFn: () => api<Vacancy[]>('/vacancies') });
export const useTags = () => useQuery({ queryKey: ['tags'], queryFn: () => api<Tag[]>('/tags') });
export const useUsers = () => useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/users') });

export const notifyError = (e: unknown) =>
  notifications.show({ color: 'red', title: 'Ошибка', message: e instanceof Error ? e.message : String(e) });
export const notifyOk = (message: string) => notifications.show({ color: 'teal', message });

export const vacancyLabel = (v: { title: string; city: string }) => `${v.title} · ${v.city}`;
