import { Badge, Button, Checkbox, Group, Paper, Select, Stack, Text } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, qs, type Interview, type Slot } from '../api';
import { notifyError, notifyOk } from '../hooks';
import { dayLabel, INTERVIEW_STATUS, time } from '../labels';

export default function CandidateInterviews({ candidateId, vacancyId }: { candidateId: number; vacancyId: number | null }) {
  const qc = useQueryClient();
  const [slotId, setSlotId] = useState<string | null>(null);
  const [notify, setNotify] = useState(true);
  const list = useQuery({ queryKey: ['candidate-interviews', candidateId], queryFn: () => api<Interview[]>(`/candidates/${candidateId}/interviews`) });
  const free = useQuery({ queryKey: ['slots-available', vacancyId], queryFn: () => api<Slot[]>(`/slots/available${qs({ vacancy_id: vacancyId })}`) });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['candidate-interviews', candidateId] });
    void qc.invalidateQueries({ queryKey: ['slots'] });
    void qc.invalidateQueries({ queryKey: ['slots-available'] });
    void qc.invalidateQueries({ queryKey: ['candidate', candidateId] });
    void qc.invalidateQueries({ queryKey: ['candidates'] });
  };
  const book = useMutation({
    mutationFn: () => api(`/candidates/${candidateId}/interviews`, { method: 'POST', json: { slot_id: Number(slotId), vacancy_id: vacancyId, notify } }),
    onSuccess: () => { notifyOk('Кандидат записан'); setSlotId(null); refresh(); },
    onError: notifyError,
  });
  const mark = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api(`/interviews/${id}`, { method: 'PATCH', json: { status } }),
    onSuccess: refresh, onError: notifyError,
  });
  const active = (list.data ?? []).filter((i) => i.status !== 'rescheduled');

  return (
    <Stack gap="xs">
      {active.length === 0 && <Text size="sm" c="dimmed">Записей нет</Text>}
      {active.map((i) => {
        const started = new Date(i.starts_at).getTime() <= Date.now() + 3600_000;
        return (
          <Paper key={i.id} withBorder p="xs">
            <Group justify="space-between">
              <div>
                <Text size="sm" fw={500}>{dayLabel(i.starts_at)}, {time(i.starts_at)}</Text>
                <Text size="xs" c="dimmed">{i.address} · {i.recruiter_name}{i.vacancy_title ? ` · ${i.vacancy_title}` : ''}</Text>
                <Text size="xs" c="dimmed">
                  {i.booked_via === 'bot' ? 'записался сам' : 'записал рекрутер'}
                  {i.confirmed_at ? ' · подтвердил ✓' : ''}{i.reminded_24h_at ? ' · напомнили за сутки' : ''}{i.reminded_2h_at ? ' · за 2 часа' : ''}
                </Text>
              </div>
              <Group gap={4}>
                <Badge color={INTERVIEW_STATUS[i.status]?.color} variant="light">{INTERVIEW_STATUS[i.status]?.label}</Badge>
                {i.status === 'booked' && (
                  <>
                    <Button size="compact-xs" variant="light" color="teal" disabled={!started} onClick={() => mark.mutate({ id: i.id, status: 'attended' })}>Пришёл</Button>
                    <Button size="compact-xs" variant="light" color="red" disabled={!started} onClick={() => mark.mutate({ id: i.id, status: 'no_show' })}>Не пришёл</Button>
                    <Button size="compact-xs" variant="subtle" color="gray" onClick={() => window.confirm('Отменить запись?') && mark.mutate({ id: i.id, status: 'cancelled' })}>Отменить</Button>
                  </>
                )}
              </Group>
            </Group>
          </Paper>
        );
      })}
      <Group align="flex-end" wrap="nowrap">
        <Select style={{ flex: 1 }} size="xs" placeholder={(free.data ?? []).length ? 'Записать на свободное время…' : 'Свободных слотов нет — добавьте в «Собеседованиях»'}
          value={slotId} onChange={setSlotId} searchable
          data={(free.data ?? []).map((s) => ({ value: String(s.id), label: `${dayLabel(s.starts_at)}, ${time(s.starts_at)} · ${s.recruiter_name} (${s.booked}/${s.capacity})` }))} />
        <Checkbox size="xs" label="Сообщить в WhatsApp" checked={notify} onChange={(e) => setNotify(e.currentTarget.checked)} />
        <Button size="xs" disabled={!slotId} loading={book.isPending} onClick={() => book.mutate()}>Записать</Button>
      </Group>
      <Text size="xs" c="dimmed">Сообщение уйдёт, только если кандидат писал в последние 24 часа. Иначе кандидата нужно предупредить звонком; напоминания придут автоматически.</Text>
    </Stack>
  );
}
