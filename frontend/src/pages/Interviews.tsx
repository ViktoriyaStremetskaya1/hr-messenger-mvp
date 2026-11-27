import {
  ActionIcon, Badge, Button, Group, Menu, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Text, TextInput, Title, Tooltip,
} from '@mantine/core';
import { IconCheck, IconDots, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, qs, type Slot } from '../api';
import { useAuth } from '../auth';
import CandidateDrawer from '../components/CandidateDrawer';
import { notifyError, notifyOk, useUsers, useVacancies, vacancyLabel } from '../hooks';
import { dayKey, dayLabel, INTERVIEW_STATUS, time, todayKey } from '../labels';

export default function InterviewsPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const users = useUsers();
  const vacancies = useVacancies();
  const [recruiter, setRecruiter] = useState<string | null>(user?.role === 'recruiter' ? String(user.id) : null);
  const [vacancy, setVacancy] = useState<string | null>(null);
  const [create, setCreate] = useState(false);
  const [openCandidate, setOpenCandidate] = useState<number | null>(null);
  const params = { recruiter_id: recruiter, vacancy_id: vacancy };
  const slots = useQuery({ queryKey: ['slots', params], queryFn: () => api<Slot[]>(`/slots${qs(params)}`), refetchInterval: 15_000 });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['slots'] });

  const mark = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api(`/interviews/${id}`, { method: 'PATCH', json: { status } }),
    onSuccess: refresh, onError: notifyError,
  });
  const slotAct = useMutation({
    mutationFn: ({ id, method, json }: { id: number; method: string; json?: object }) => api(`/slots/${id}`, { method, json }),
    onSuccess: refresh, onError: notifyError,
  });

  const byDay = new Map<string, Slot[]>();
  for (const s of slots.data ?? []) {
    const k = dayKey(s.starts_at);
    byDay.set(k, [...(byDay.get(k) ?? []), s]);
  }
  const now = Date.now();
  const total = (slots.data ?? []).reduce((a, s) => a + s.capacity, 0);
  const booked = (slots.data ?? []).reduce((a, s) => a + s.booked, 0);

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Собеседования</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreate(true)}>Добавить слоты</Button>
      </Group>
      <Group mb="md" align="flex-end">
        <Select placeholder="Все рекрутеры" clearable value={recruiter} onChange={setRecruiter} w={220}
          data={(users.data ?? []).filter((u) => u.is_active).map((u) => ({ value: String(u.id), label: u.full_name }))} />
        <Select placeholder="Все вакансии" clearable searchable value={vacancy} onChange={setVacancy} w={260}
          data={(vacancies.data ?? []).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
        <Text size="sm" c="dimmed">Ближайшие 14 дней · занято {booked} из {total} мест</Text>
      </Group>

      {byDay.size === 0 && !slots.isLoading && (
        <Paper withBorder p="lg"><Text c="dimmed" ta="center">Слотов нет. Нажмите «Добавить слоты» — кандидаты смогут выбрать время прямо в WhatsApp.</Text></Paper>
      )}
      <Stack>
        {[...byDay.entries()].map(([day, list]) => (
          <Paper key={day} withBorder p="sm">
            <Text fw={600} mb="xs">{dayLabel(list[0].starts_at)}{day === todayKey() ? ' · сегодня' : ''}</Text>
            <Stack gap={6}>
              {list.map((s) => {
                const started = new Date(s.starts_at).getTime() <= now + 3600_000;
                return (
                  <Group key={s.id} wrap="nowrap" align="flex-start" gap="sm" style={{ opacity: s.is_active ? 1 : 0.5 }}>
                    <Text ff="monospace" fw={600} w={120} style={{ whiteSpace: 'nowrap' }}>{time(s.starts_at)}–{time(s.ends_at)}</Text>
                    <Stack gap={2} style={{ flex: 1 }}>
                      <Group gap={6}>
                        <Text size="sm">{s.recruiter_name}</Text>
                        <Text size="xs" c="dimmed">{s.vacancy_title ?? 'любая вакансия'}{s.office_address ? ` · ${s.office_address}` : ''}</Text>
                        <Badge size="xs" variant="light" color={s.booked >= s.capacity ? 'red' : 'teal'}>{s.booked}/{s.capacity}</Badge>
                        {!s.is_active && <Badge size="xs" color="gray">выключен</Badge>}
                      </Group>
                      <Group gap={6}>
                        {s.bookings.map((b) => (
                          <Group key={b.interview_id} gap={2} wrap="nowrap">
                            <Badge variant="light" color={INTERVIEW_STATUS[b.status]?.color} tt="none" style={{ cursor: 'pointer' }}
                              onClick={() => setOpenCandidate(b.candidate_id)}
                              leftSection={b.confirmed_at ? <IconCheck size={12} /> : undefined}>
                              {b.candidate_name} · {INTERVIEW_STATUS[b.status]?.label}
                            </Badge>
                            {b.status === 'booked' && (
                              <Menu position="bottom-start">
                                <Menu.Target><ActionIcon size="xs" variant="subtle" aria-label="Действия"><IconDots size={14} /></ActionIcon></Menu.Target>
                                <Menu.Dropdown>
                                  <Menu.Item disabled={!started} onClick={() => mark.mutate({ id: b.interview_id, status: 'attended' })}>Пришёл</Menu.Item>
                                  <Menu.Item disabled={!started} onClick={() => mark.mutate({ id: b.interview_id, status: 'no_show' })}>Не пришёл</Menu.Item>
                                  <Menu.Divider />
                                  <Menu.Item color="red" onClick={() => window.confirm('Отменить запись?') && mark.mutate({ id: b.interview_id, status: 'cancelled' })}>Отменить запись</Menu.Item>
                                </Menu.Dropdown>
                              </Menu>
                            )}
                          </Group>
                        ))}
                      </Group>
                    </Stack>
                    <Group gap={4}>
                      <Tooltip label={s.is_active ? 'Выключить (не предлагать кандидатам)' : 'Включить'}>
                        <Switch size="xs" checked={s.is_active} onChange={(e) => slotAct.mutate({ id: s.id, method: 'PATCH', json: { is_active: e.currentTarget.checked } })} />
                      </Tooltip>
                      {s.booked === 0 && (
                        <ActionIcon size="sm" variant="subtle" color="red" aria-label="Удалить слот" onClick={() => slotAct.mutate({ id: s.id, method: 'DELETE' })}>
                          <IconTrash size={14} />
                        </ActionIcon>
                      )}
                    </Group>
                  </Group>
                );
              })}
            </Stack>
          </Paper>
        ))}
      </Stack>
      {create && <CreateSlots onClose={() => setCreate(false)} />}
      <CandidateDrawer id={openCandidate} onClose={() => setOpenCandidate(null)} />
    </>
  );
}

function CreateSlots({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { user, can } = useAuth();
  const users = useUsers();
  const vacancies = useVacancies();
  const [f, setF] = useState({
    recruiter_id: String(user?.id ?? ''), vacancy_id: null as string | null, date: todayKey(), start: '10:00', end: '13:00',
    duration_min: 30, capacity: 1, office_address: '',
  });
  const n = (() => {
    const [h1, m1] = f.start.split(':').map(Number);
    const [h2, m2] = f.end.split(':').map(Number);
    return Math.max(0, Math.floor((h2 * 60 + m2 - h1 * 60 - m1) / (f.duration_min || 1)));
  })();
  const save = useMutation({
    mutationFn: () => api<Slot[]>('/slots/bulk', { method: 'POST', json: {
      ...f, recruiter_id: Number(f.recruiter_id), vacancy_id: f.vacancy_id ? Number(f.vacancy_id) : null, office_address: f.office_address || null } }),
    onSuccess: (r) => { notifyOk(`Создано слотов: ${r.length}`); void qc.invalidateQueries({ queryKey: ['slots'] }); onClose(); },
    onError: notifyError,
  });
  return (
    <Modal opened onClose={onClose} title="Добавить слоты" size="lg">
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select label="Рекрутер" disabled={!can('admin', 'lead')} value={f.recruiter_id} onChange={(v) => v && setF({ ...f, recruiter_id: v })}
            data={(users.data ?? []).filter((u) => u.is_active).map((u) => ({ value: String(u.id), label: u.full_name }))} />
          <Select label="Вакансия" placeholder="Любая" clearable searchable value={f.vacancy_id} onChange={(v) => setF({ ...f, vacancy_id: v })}
            data={(vacancies.data ?? []).filter((v) => v.is_active).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
          <TextInput type="date" label="Дата" value={f.date} min={todayKey()} onChange={(e) => setF({ ...f, date: e.currentTarget.value })} />
          <Group grow>
            <TextInput type="time" label="С" value={f.start} onChange={(e) => setF({ ...f, start: e.currentTarget.value })} />
            <TextInput type="time" label="До" value={f.end} onChange={(e) => setF({ ...f, end: e.currentTarget.value })} />
          </Group>
          <NumberInput label="Длительность слота, мин" min={10} max={480} step={5} value={f.duration_min} onChange={(v) => setF({ ...f, duration_min: Number(v) || 30 })} />
          <NumberInput label="Мест в слоте" description="Больше 1 — групповое собеседование" min={1} max={100} value={f.capacity}
            onChange={(v) => setF({ ...f, capacity: Number(v) || 1 })} />
        </SimpleGrid>
        <TextInput label="Адрес" placeholder="Пусто — адрес из карточки вакансии" value={f.office_address} onChange={(e) => setF({ ...f, office_address: e.currentTarget.value })} />
        <Text size="sm" c="dimmed">Будет создано слотов: {n}. Время — Алматы. Бот предлагает кандидатам слоты не раньше чем через 2 часа и не дальше 14 дней.</Text>
        <Group justify="flex-end"><Button disabled={n === 0} loading={save.isPending} onClick={() => save.mutate()}>Создать</Button></Group>
      </Stack>
    </Modal>
  );
}
