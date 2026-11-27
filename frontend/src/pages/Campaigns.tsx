import {
  Alert, Badge, Button, Group, Modal, MultiSelect, Paper, Progress, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Title,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconPlus } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api, type Campaign, type CampaignSegment, type Scenario, type SegmentPreview } from '../api';
import { notifyError, notifyOk, useTags, useVacancies, vacancyLabel } from '../hooks';
import { dt, screeningOptions, statusOptions } from '../labels';

export const CAMPAIGN_STATUS: Record<Campaign['status'], { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'gray' }, scheduled: { label: 'Запланирована', color: 'blue' },
  running: { label: 'Идёт', color: 'teal' }, paused: { label: 'Пауза', color: 'yellow' },
  done: { label: 'Завершена', color: 'green' }, cancelled: { label: 'Отменена', color: 'red' },
};
export const SKIP_REASON: Record<string, string> = {
  unsubscribed: 'отписались', frequency: 'частота касаний', active_scenario: 'уже в диалоге', cancelled: 'отмена',
  deleted: 'удалены', error: 'ошибка', other: 'другое',
};

/** Сценарий годится для рассылки: после выбора языка — шаблон. */
export function campaignReady(s: Scenario): boolean {
  if (!s.is_active || s.kind === 'reminder') return false;
  let n = s.graph.nodes[s.graph.start];
  for (let i = 0; i < 5 && n?.type === 'language'; i++) n = s.graph.nodes[n.next ?? ''];
  return n?.type === 'template';
}

export default function CampaignsPage() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const preselected = (params.get('ids') ?? '').split(',').filter(Boolean).map(Number);
  const [open, setOpen] = useState(preselected.length > 0);
  const list = useQuery({ queryKey: ['campaigns'], queryFn: () => api<Campaign[]>('/campaigns'), refetchInterval: 10_000 });

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Рассылки</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setOpen(true)}>Новая рассылка</Button>
      </Group>
      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table highlightOnHover miw={800}>
          <Table.Thead><Table.Tr><Table.Th>Название</Table.Th><Table.Th>Статус</Table.Th><Table.Th w={220}>Прогресс</Table.Th>
            <Table.Th>Доставлено</Table.Th><Table.Th>Ответили</Table.Th><Table.Th>Подходят</Table.Th><Table.Th>Создана</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(list.data ?? []).map((c) => {
              const s = c.stats;
              const done = (s.total ?? 0) - (s.queued ?? 0);
              return (
                <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/campaigns/${c.id}`)}>
                  <Table.Td fw={500}>{c.name}</Table.Td>
                  <Table.Td><Badge color={CAMPAIGN_STATUS[c.status].color} variant="light">{CAMPAIGN_STATUS[c.status].label}</Badge></Table.Td>
                  <Table.Td>
                    {s.total ? (<><Progress value={(done / s.total) * 100} size="sm" /><Text size="xs" c="dimmed">{done} из {s.total} · отправлено {s.sent}</Text></>) : '—'}
                  </Table.Td>
                  <Table.Td>{s.delivered ?? '—'}</Table.Td>
                  <Table.Td>{s.replied ?? '—'}</Table.Td>
                  <Table.Td>{s.screening_fit ?? '—'}</Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{dt(c.created_at)}</Text></Table.Td>
                </Table.Tr>
              );
            })}
            {!list.isLoading && (list.data ?? []).length === 0 && (
              <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Рассылок пока нет</Text></Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      {open && <CampaignForm preselected={preselected} onClose={() => { setOpen(false); if (preselected.length) setParams({}); }} />}
    </>
  );
}

function CampaignForm({ preselected, onClose }: { preselected: number[]; onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const vacancies = useVacancies();
  const tags = useTags();
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: () => api<Scenario[]>('/scenarios') });
  const [name, setName] = useState('');
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [vacancyId, setVacancyId] = useState<string | null>(null);
  const [seg, setSeg] = useState<CampaignSegment>(preselected.length ? { candidate_ids: preselected } : {});
  const [when, setWhen] = useState<'now' | 'later'>('now');
  const [at, setAt] = useState('');
  const [debSeg] = useDebouncedValue(seg, 400);
  const preview = useQuery({
    queryKey: ['campaign-preview', debSeg],
    queryFn: () => api<SegmentPreview>('/campaigns/preview', { method: 'POST', json: debSeg }),
  });
  useEffect(() => {
    if (vacancyId && !seg.vacancy_ids?.length && !preselected.length) setSeg((s) => ({ ...s, vacancy_ids: [Number(vacancyId)] }));
  }, [vacancyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const ready = (scenarios.data ?? []).filter(campaignReady);
  const cities = Array.from(new Set((vacancies.data ?? []).map((v) => v.city))).sort();
  const vacOpts = (vacancies.data ?? []).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }));
  const scheduledAt = when === 'later' && at ? `${at}:00+05:00` : null; // время Алматы (UTC+5)

  const submit = useMutation({
    mutationFn: async (launch: boolean) => {
      const c = await api<Campaign>('/campaigns', { method: 'POST', json: {
        name, scenario_id: Number(scenarioId), vacancy_id: vacancyId ? Number(vacancyId) : null, segment: seg, scheduled_at: scheduledAt } });
      if (launch) await api(`/campaigns/${c.id}/launch`, { method: 'POST', json: { scheduled_at: scheduledAt } });
      return { c, launch };
    },
    onSuccess: ({ c, launch }) => {
      notifyOk(launch ? (scheduledAt ? 'Рассылка запланирована' : 'Рассылка запущена') : 'Черновик сохранён');
      void qc.invalidateQueries({ queryKey: ['campaigns'] });
      onClose();
      nav(`/campaigns/${c.id}`);
    },
    onError: notifyError,
  });
  const ms = (key: keyof CampaignSegment, numeric = false) => ({
    value: ((seg[key] as (string | number)[] | undefined) ?? []).map(String),
    onChange: (v: string[]) => setSeg({ ...seg, [key]: numeric ? v.map(Number) : v }),
    clearable: true,
  });
  const p = preview.data;
  const valid = name.trim() && scenarioId && (when === 'now' || at);

  return (
    <Modal opened onClose={onClose} title="Новая рассылка" size="xl">
      <Stack>
        <TextInput label="Название" placeholder="Операционисты Алматы, ноябрь" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select label="Сценарий" required data={ready.map((s) => ({ value: String(s.id), label: s.name }))} value={scenarioId} onChange={setScenarioId}
            description={ready.length ? 'Первое сообщение — одобренный шаблон' : 'Нет подходящих сценариев: создайте «Предложение вакансии» или «Недозвон»'} />
          <Select label="Вакансия" searchable clearable data={vacOpts.filter((o) => vacancies.data?.find((v) => String(v.id) === o.value)?.is_active)}
            value={vacancyId} onChange={setVacancyId} description="О какой вакансии пишем (подставится в шаблон)" />
        </SimpleGrid>

        <Paper withBorder p="sm">
          <Text fw={500} mb="xs">Кому</Text>
          {preselected.length > 0 ? (
            <Group><Text size="sm">Выбрано в списке кандидатов: {preselected.length}</Text>
              <Button size="xs" variant="subtle" onClick={() => setSeg({})}>Задать сегмент вместо этого</Button></Group>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <MultiSelect label="Город" data={cities} {...ms('cities')} />
              <MultiSelect label="Откликались на вакансии" data={vacOpts} searchable {...ms('vacancy_ids', true)} />
              <MultiSelect label="Статус" data={statusOptions} {...ms('statuses')} />
              <MultiSelect label="Скрининг" data={screeningOptions} {...ms('screening')} />
              <Select label="Кадровый резерв" clearable data={[{ value: 'true', label: 'Только резерв' }, { value: 'false', label: 'Без резерва' }]}
                value={seg.is_reserve == null ? null : String(seg.is_reserve)} onChange={(v) => setSeg({ ...seg, is_reserve: v == null ? null : v === 'true' })} />
              <MultiSelect label="Теги" data={(tags.data ?? []).map((t) => ({ value: String(t.id), label: t.name }))} {...ms('tag_ids', true)} />
              <MultiSelect label="Язык" data={[{ value: 'ru', label: 'Русский' }, { value: 'kk', label: 'Қазақша' }, { value: 'none', label: 'Не выбран' }]} {...ms('languages')} />
            </SimpleGrid>
          )}
          {p && (
            <Alert mt="sm" color={p.eligible ? 'teal' : 'orange'} p="xs">
              <Text size="sm">В сегменте: <b>{p.total}</b>, получат сообщение: <b>{p.eligible}</b>
                {Object.entries(p.excluded).filter(([, n]) => n).map(([k, n]) => ` · ${SKIP_REASON[k] ?? k}: ${n}`).join('')}</Text>
              {p.sample.length > 0 && <Text size="xs" c="dimmed">Например: {p.sample.join(', ')}</Text>}
            </Alert>
          )}
        </Paper>

        <Group align="flex-end">
          <SegmentedControl value={when} onChange={(v) => setWhen(v as 'now' | 'later')} data={[{ value: 'now', label: 'Сразу' }, { value: 'later', label: 'Запланировать' }]} />
          {when === 'later' && <TextInput type="datetime-local" label="Дата и время (Алматы)" value={at} onChange={(e) => setAt(e.currentTarget.value)} />}
        </Group>
        <Text size="xs" c="dimmed">Сообщения уходят только в рабочие часы и с учётом лимитов из «Настроек». Кандидаты, которым писали недавно, отписавшиеся и те, с кем уже идёт диалог, будут пропущены.</Text>
        <Group justify="flex-end">
          <Button variant="default" disabled={!valid} loading={submit.isPending} onClick={() => submit.mutate(false)}>Сохранить черновик</Button>
          <Button disabled={!valid || !p?.eligible} loading={submit.isPending}
            onClick={() => window.confirm(`Отправить рассылку ${p?.eligible} кандидатам?`) && submit.mutate(true)}>
            {when === 'later' ? 'Запланировать' : 'Запустить'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
