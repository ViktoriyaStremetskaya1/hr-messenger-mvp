import { ActionIcon, Badge, Box, Button, Grid, Group, Indicator, NavLink, Paper, ScrollArea, Select, Stack, Text, TextInput, Title, Tooltip } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconArrowLeft, IconRobot, IconSearch, IconUser, IconUserCheck } from '@tabler/icons-react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, qs, type InboxCounts, type InboxItem, type Page } from '../api';
import { useAuth } from '../auth';
import CandidateDrawer from '../components/CandidateDrawer';
import Chat from '../components/Chat';
import { notifyError, useUsers, useVacancies, vacancyLabel } from '../hooks';

const FILTERS: { key: keyof InboxCounts; label: string }[] = [
  { key: 'needs_reply', label: 'Ждут ответа' }, { key: 'mine', label: 'Мои' }, { key: 'unassigned', label: 'Без ответственного' },
  { key: 'unread', label: 'Непрочитанные' }, { key: 'bot', label: 'Ведёт бот' }, { key: 'human', label: 'У рекрутера' }, { key: 'all', label: 'Все' },
];

function ago(s: string | null): string {
  if (!s) return '';
  const d = new Date(s);
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Almaty' }) === d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Almaty' });
  return today ? d.toLocaleTimeString('ru-RU', { timeZone: 'Asia/Almaty', hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('ru-RU', { timeZone: 'Asia/Almaty', day: 'numeric', month: 'short' });
}

export default function InboxPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const users = useUsers();
  const vacancies = useVacancies();
  const narrow = useMediaQuery('(max-width: 62em)');
  const [filter, setFilter] = useState<keyof InboxCounts>('needs_reply');
  const [q, setQ] = useState('');
  const [vacancy, setVacancy] = useState<string | null>(null);
  const [dq] = useDebouncedValue(q, 300);
  const [sel, setSel] = useState<InboxItem | null>(null);
  const [card, setCard] = useState<number | null>(null);

  const params = { filter, q: dq, vacancy_id: vacancy, page_size: 100 };
  const list = useQuery({ queryKey: ['inbox', params], queryFn: () => api<Page<InboxItem>>(`/inbox${qs(params)}`),
    placeholderData: keepPreviousData, refetchInterval: 30_000 });
  const counts = useQuery({ queryKey: ['inbox-counts'], queryFn: () => api<InboxCounts>('/inbox/counts'), refetchInterval: 30_000 });
  const current = sel ? (list.data?.items.find((i) => i.conversation_id === sel.conversation_id) ?? sel) : null;
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['inbox'] }); void qc.invalidateQueries({ queryKey: ['inbox-counts'] }); void qc.invalidateQueries({ queryKey: ['conversation'] }); };
  const act = useMutation({
    mutationFn: ({ path, json }: { path: string; json?: object }) => api(path, { method: 'POST', json }),
    onSuccess: refresh, onError: notifyError,
  });

  const listPane = (
    <Stack gap="xs" h="100%">
      <Group gap="xs" wrap="nowrap">
        <TextInput style={{ flex: 1 }} size="xs" placeholder="Имя или 4 цифры телефона" leftSection={<IconSearch size={14} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} />
        <Select size="xs" w={170} placeholder="Вакансия" clearable searchable value={vacancy} onChange={setVacancy}
          data={(vacancies.data ?? []).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
      </Group>
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack gap={0}>
          {(list.data?.items ?? []).map((i) => (
            <Box key={i.conversation_id} p="xs" onClick={() => setSel(i)} style={{
              cursor: 'pointer', borderBottom: '1px solid var(--mantine-color-default-border)',
              background: current?.conversation_id === i.conversation_id ? 'var(--mantine-color-teal-light)' : undefined }}>
              <Group justify="space-between" wrap="nowrap" gap={6}>
                <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                  {i.needs_reply && <Tooltip label="Ждёт ответа"><Indicator color="orange" size={8} processing><span /></Indicator></Tooltip>}
                  <Text size="sm" fw={i.unread_count ? 700 : 500} truncate>{i.candidate_name}</Text>
                  {i.mode === 'bot' && i.scenario_step && <Tooltip label={`Бот: ${i.scenario_name} · ${i.scenario_step}`}><IconRobot size={14} color="var(--mantine-color-blue-6)" /></Tooltip>}
                </Group>
                <Group gap={4} wrap="nowrap">
                  {i.unread_count > 0 && <Badge size="xs" circle>{i.unread_count}</Badge>}
                  <Text size="xs" c="dimmed">{ago(i.last_message_at)}</Text>
                </Group>
              </Group>
              <Text size="xs" c="dimmed" truncate>{i.last_direction === 'out' ? '↩ ' : ''}{i.last_preview}</Text>
              <Group gap={4} mt={2}>
                {i.vacancy && <Badge size="xs" variant="outline" tt="none">{i.vacancy}</Badge>}
                {i.assignee_name ? <Badge size="xs" variant="light" color="gray" tt="none" leftSection={<IconUser size={10} />}>{i.assignee_name}</Badge>
                  : <Badge size="xs" variant="light" color="orange" tt="none">без ответственного</Badge>}
                {i.unsubscribed && <Badge size="xs" color="red" variant="light">отписался</Badge>}
              </Group>
            </Box>
          ))}
          {!list.isLoading && (list.data?.items ?? []).length === 0 && <Text size="sm" c="dimmed" ta="center" py="xl">Диалогов нет</Text>}
        </Stack>
      </ScrollArea>
    </Stack>
  );

  const chatPane = current ? (
    <Stack gap="xs">
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="xs">
          {narrow && <ActionIcon variant="subtle" onClick={() => setSel(null)} aria-label="Назад"><IconArrowLeft size={18} /></ActionIcon>}
          <div>
            <Text fw={600} style={{ cursor: 'pointer' }} onClick={() => setCard(current.candidate_id)}>{current.candidate_name}</Text>
            <Text size="xs" c="dimmed">{current.phone_masked}{current.city ? ` · ${current.city}` : ''}{current.vacancy ? ` · ${current.vacancy}` : ''}</Text>
          </div>
        </Group>
        <Group gap={6}>
          <Select size="xs" w={190} placeholder="Ответственный" clearable={can('admin', 'lead')} value={current.assignee_id ? String(current.assignee_id) : null}
            data={(users.data ?? []).filter((u) => u.is_active).map((u) => ({ value: String(u.id), label: u.full_name }))}
            onChange={(v) => act.mutate({ path: `/conversations/${current.conversation_id}/assign`, json: { user_id: v ? Number(v) : null } })} />
          {current.mode === 'bot' && current.scenario_step ? (
            <Button size="xs" variant="light" leftSection={<IconUserCheck size={14} />} onClick={() => act.mutate({ path: `/conversations/${current.conversation_id}/takeover` })}>Перехватить у бота</Button>
          ) : current.mode === 'human' && current.scenario_step ? (
            <Button size="xs" variant="light" color="blue" leftSection={<IconRobot size={14} />} onClick={() => act.mutate({ path: `/candidates/${current.candidate_id}/bot` })}>Вернуть боту</Button>
          ) : null}
          {current.needs_reply && <Button size="xs" variant="subtle" color="gray" onClick={() => act.mutate({ path: `/conversations/${current.conversation_id}/done` })}>Обработано</Button>}
          <Button size="xs" variant="default" onClick={() => setCard(current.candidate_id)}>Карточка</Button>
        </Group>
      </Group>
      <Chat key={current.candidate_id} candidateId={current.candidate_id} candidateName={current.candidate_name} />
    </Stack>
  ) : <Text c="dimmed" ta="center" mt="xl">Выберите диалог слева</Text>;

  return (
    <>
      <Group justify="space-between" mb="sm">
        <Title order={2}>Чаты</Title>
      </Group>
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 2 }} display={narrow && current ? 'none' : undefined}>
          <Paper withBorder p={4}>
            {FILTERS.map((f) => (
              <NavLink key={f.key} active={filter === f.key} label={f.label} onClick={() => setFilter(f.key)}
                rightSection={counts.data && counts.data[f.key] > 0 ? (
                  <Badge size="xs" variant={f.key === 'needs_reply' ? 'filled' : 'light'} color={f.key === 'needs_reply' ? 'orange' : 'gray'}>{counts.data[f.key]}</Badge>
                ) : null} />
            ))}
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }} display={narrow && current ? 'none' : undefined}>
          <Paper withBorder p="xs" h="calc(100vh - 150px)">{listPane}</Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }} display={narrow && !current ? 'none' : undefined}>
          <Paper withBorder p="sm" mih="calc(100vh - 150px)">{chatPane}</Paper>
        </Grid.Col>
      </Grid>
      <CandidateDrawer id={card} onClose={() => setCard(null)} />
    </>
  );
}
