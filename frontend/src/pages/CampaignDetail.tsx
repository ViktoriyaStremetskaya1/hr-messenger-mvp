import { ActionIcon, Badge, Button, Group, Pagination, Paper, Progress, SegmentedControl, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api, qs, type Campaign, type CampaignRecipient, type Page, type Scenario } from '../api';
import { notifyError, useVacancies, vacancyLabel } from '../hooks';
import { dt } from '../labels';
import { CAMPAIGN_STATUS, SKIP_REASON } from './Campaigns';

const R_STATUS: Record<string, { label: string; color: string }> = {
  queued: { label: 'в очереди', color: 'gray' }, sent: { label: 'отправлено', color: 'teal' },
  skipped: { label: 'пропущен', color: 'yellow' }, failed: { label: 'ошибка', color: 'red' },
};
const M_STATUS: Record<string, string> = { queued: '🕓', sent: '✓', delivered: '✓✓', read: '✓✓ прочитано', failed: '⚠ не доставлено' };

export default function CampaignDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const vacancies = useVacancies();
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const c = useQuery({ queryKey: ['campaign', id], queryFn: () => api<Campaign>(`/campaigns/${id}`), refetchInterval: 5000 });
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: () => api<Scenario[]>('/scenarios') });
  const params = { status: filter === 'all' ? undefined : filter, page, page_size: 50 };
  const rec = useQuery({
    queryKey: ['campaign-recipients', id, params], refetchInterval: 5000, placeholderData: keepPreviousData,
    queryFn: () => api<Page<CampaignRecipient>>(`/campaigns/${id}/recipients${qs(params)}`),
  });
  const act = useMutation({
    mutationFn: (path: string) => api<Campaign>(`/campaigns/${id}/${path}`, { method: 'POST' }),
    onSuccess: (d) => { qc.setQueryData(['campaign', id], d); void qc.invalidateQueries({ queryKey: ['campaign-recipients', id] }); },
    onError: notifyError,
  });
  const camp = c.data;
  if (!camp) return <Text>Загрузка…</Text>;
  const s = camp.stats;
  const vac = vacancies.data?.find((v) => v.id === camp.vacancy_id);
  const sc = scenarios.data?.find((x) => x.id === camp.scenario_id);
  const sent = s.sent ?? 0;
  const funnel: [string, number | undefined][] = [
    ['Отправлено', s.sent], ['Доставлено', s.delivered], ['Прочитано', s.read], ['Ответили', s.replied],
    ['Прошли скрининг', s.screening_fit], ['Записаны', s.booked], ['Пришли', s.attended],
  ];

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <ActionIcon variant="subtle" onClick={() => nav('/campaigns')} aria-label="Назад"><IconArrowLeft /></ActionIcon>
          <Title order={2}>{camp.name}</Title>
          <Badge color={CAMPAIGN_STATUS[camp.status].color} variant="light">{CAMPAIGN_STATUS[camp.status].label}</Badge>
        </Group>
        <Group>
          {camp.status === 'draft' && <Button onClick={() => window.confirm('Запустить рассылку?') && act.mutate('launch')}>Запустить</Button>}
          {['scheduled', 'running'].includes(camp.status) && <Button variant="default" onClick={() => act.mutate('pause')}>Пауза</Button>}
          {camp.status === 'paused' && <Button onClick={() => act.mutate('resume')}>Продолжить</Button>}
          {['scheduled', 'running', 'paused'].includes(camp.status) && (
            <Button color="red" variant="subtle" onClick={() => window.confirm('Отменить рассылку? Оставшимся сообщения не уйдут.') && act.mutate('cancel')}>Отменить</Button>
          )}
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        Сценарий: {sc?.name ?? `#${camp.scenario_id}`}{vac ? ` · вакансия: ${vacancyLabel(vac)}` : ''}
        {camp.scheduled_at ? ` · старт: ${dt(camp.scheduled_at)}` : ''}{camp.started_at ? ` · начата ${dt(camp.started_at)}` : ''}
        {camp.finished_at ? ` · завершена ${dt(camp.finished_at)}` : ''}
      </Text>
      {camp.status === 'running' && (s.queued ?? 0) > 0 && (
        <Text size="sm" c="teal">Отправка идёт порциями (лимит в минуту из «Настроек»), вне рабочих часов — пауза до утра. В очереди: {s.queued}.</Text>
      )}

      {camp.status !== 'draft' && (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          <Paper withBorder p="md">
            <Text fw={500} mb="sm">Воронка</Text>
            <Stack gap={8}>
              {funnel.map(([label, n]) => (
                <div key={label}>
                  <Group justify="space-between"><Text size="sm">{label}</Text>
                    <Text size="sm" fw={500}>{n ?? 0}{sent > 0 && label !== 'Отправлено' ? ` · ${Math.round(((n ?? 0) / sent) * 100)}%` : ''}</Text></Group>
                  <Progress value={sent ? ((n ?? 0) / sent) * 100 : 0} size="sm" />
                </div>
              ))}
            </Stack>
          </Paper>
          <Paper withBorder p="md">
            <Text fw={500} mb="sm">Получатели</Text>
            <SimpleGrid cols={2}>
              <Stat label="Всего" v={s.total} /><Stat label="В очереди" v={s.queued} />
              <Stat label="Отправлено" v={s.sent} /><Stat label="Ошибки" v={s.failed} />
            </SimpleGrid>
            {(s.skipped ?? 0) > 0 && (
              <Text size="sm" mt="sm">Пропущено {s.skipped}: {Object.entries(s.skipped_by_reason ?? {}).map(([k, n]) => `${SKIP_REASON[k] ?? k} — ${n}`).join(', ')}</Text>
            )}
          </Paper>
        </SimpleGrid>
      )}

      <Paper withBorder p="sm">
        <Group justify="space-between" mb="xs">
          <SegmentedControl size="xs" value={filter} onChange={(v) => { setFilter(v); setPage(1); }}
            data={[{ value: 'all', label: 'Все' }, { value: 'queued', label: 'В очереди' }, { value: 'sent', label: 'Отправлено' },
              { value: 'skipped', label: 'Пропущены' }, { value: 'failed', label: 'Ошибки' }]} />
          <Text size="xs" c="dimmed">{rec.data?.total ?? 0}</Text>
        </Group>
        <Table fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Кандидат</Table.Th><Table.Th>Статус</Table.Th><Table.Th>Доставка</Table.Th><Table.Th>Когда</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(rec.data?.items ?? []).map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>{r.candidate_name}</Table.Td>
                <Table.Td>
                  <Badge size="sm" variant="light" color={R_STATUS[r.status].color}>{R_STATUS[r.status].label}</Badge>
                  {r.skip_reason && <Text span size="xs" c="dimmed" ml={6}>{SKIP_REASON[r.skip_reason] ?? r.skip_reason}</Text>}
                  {r.error && <Text size="xs" c="red">{r.error}</Text>}
                </Table.Td>
                <Table.Td>{r.message_status ? M_STATUS[r.message_status] ?? r.message_status : '—'}</Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{dt(r.processed_at)}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {(rec.data?.total ?? 0) > 50 && <Group justify="center" mt="sm"><Pagination total={Math.ceil((rec.data?.total ?? 0) / 50)} value={page} onChange={setPage} /></Group>}
      </Paper>
    </Stack>
  );
}

function Stat({ label, v }: { label: string; v?: number }) {
  return <div><Text size="xs" c="dimmed">{label}</Text><Text size="lg" fw={600}>{v ?? 0}</Text></div>;
}
