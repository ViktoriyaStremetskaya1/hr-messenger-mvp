import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  MultiSelect,
  Pagination,
  Paper,
  Select,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconChevronDown, IconFileImport, IconPlus, IconSearch, IconX } from '@tabler/icons-react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, qs, type Candidate, type Page } from '../api';
import CandidateCreateModal from '../components/CandidateCreateModal';
import CandidateDrawer from '../components/CandidateDrawer';
import ImportWizard from '../components/ImportWizard';
import { notifyError, notifyOk, useTags, useVacancies, vacancyLabel } from '../hooks';
import { dt, screeningOptions, STATUS, statusOptions } from '../labels';

const PAGE_SIZE = 50;
const EMPTY = { q: '', city: null as string | null, vacancy_id: null as string | null, status: null as string | null,
  screening_result: null as string | null, is_reserve: null as string | null, unsubscribed: null as string | null, tag_id: [] as string[] };

export default function CandidatesPage() {
  const qc = useQueryClient();
  const [f, setF] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [q] = useDebouncedValue(f.q, 300);
  const [selected, setSelected] = useState<number[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const vacancies = useVacancies();
  const tags = useTags();

  const params = { ...f, q, page, page_size: PAGE_SIZE };
  const list = useQuery({
    queryKey: ['candidates', params],
    queryFn: () => api<Page<Candidate>>(`/candidates${qs(params)}`),
    placeholderData: keepPreviousData,
  });

  const set = (patch: Partial<typeof EMPTY>) => {
    setF({ ...f, ...patch });
    setPage(1);
    setSelected([]);
  };

  const bulk = useMutation({
    mutationFn: (body: { action: string; tag_id?: number; vacancy_id?: number }) =>
      api<{ affected: number }>('/candidates/bulk', { method: 'POST', json: { candidate_ids: selected, ...body } }),
    onSuccess: (r) => {
      notifyOk(`Изменено: ${r.affected}`);
      void qc.invalidateQueries({ queryKey: ['candidates'] });
    },
    onError: notifyError,
  });

  const items = list.data?.items ?? [];
  const allChecked = items.length > 0 && items.every((c) => selected.includes(c.id));
  const cities = Array.from(new Set((vacancies.data ?? []).map((v) => v.city))).sort();
  const vacOptions = (vacancies.data ?? []).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }));
  const tagOptions = (tags.data ?? []).map((t) => ({ value: String(t.id), label: t.name }));
  const hasFilters = JSON.stringify(f) !== JSON.stringify(EMPTY);

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Кандидаты</Title>
        <Group gap="xs">
          <Button variant="default" leftSection={<IconFileImport size={16} />} onClick={() => setImportOpen(true)}>
            Импорт Excel/CSV
          </Button>
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreateOpen(true)}>Добавить</Button>
        </Group>
      </Group>

      <Paper withBorder p="sm" mb="md">
        <Group gap="xs" align="flex-end" wrap="wrap">
          <TextInput placeholder="ФИО, телефон или 4 последние цифры" leftSection={<IconSearch size={16} />}
            value={f.q} onChange={(e) => set({ q: e.currentTarget.value })} w={280} />
          <Select placeholder="Город" data={cities} value={f.city} onChange={(v) => set({ city: v })} clearable searchable w={150} />
          <Select placeholder="Вакансия" data={vacOptions} value={f.vacancy_id} onChange={(v) => set({ vacancy_id: v })} clearable searchable w={240} />
          <Select placeholder="Статус" data={statusOptions} value={f.status} onChange={(v) => set({ status: v })} clearable w={190} />
          <Select placeholder="Скрининг" data={screeningOptions} value={f.screening_result} onChange={(v) => set({ screening_result: v })} clearable w={150} />
          <Select placeholder="Резерв" data={[{ value: 'true', label: 'В резерве' }, { value: 'false', label: 'Не в резерве' }]}
            value={f.is_reserve} onChange={(v) => set({ is_reserve: v })} clearable w={150} />
          <Select placeholder="Отписка" data={[{ value: 'false', label: 'Активные' }, { value: 'true', label: 'Отписались' }]}
            value={f.unsubscribed} onChange={(v) => set({ unsubscribed: v })} clearable w={140} />
          <MultiSelect placeholder="Теги" data={tagOptions} value={f.tag_id} onChange={(v) => set({ tag_id: v })} clearable w={200} />
          {hasFilters && (
            <Tooltip label="Сбросить фильтры">
              <ActionIcon variant="subtle" size="lg" onClick={() => set(EMPTY)}><IconX size={18} /></ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Paper>

      <Group justify="space-between" mb="xs">
        <Text size="sm" c="dimmed">
          Найдено: {list.data?.total ?? '…'}{selected.length > 0 && ` · выбрано: ${selected.length}`}
        </Text>
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <Button size="xs" variant="light" disabled={!selected.length} rightSection={<IconChevronDown size={14} />}>
              Действия с выбранными
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => bulk.mutate({ action: 'set_reserve' })}>Добавить в резерв</Menu.Item>
            <Menu.Item onClick={() => bulk.mutate({ action: 'unset_reserve' })}>Убрать из резерва</Menu.Item>
            <Menu.Divider />
            <Menu.Label>Добавить тег</Menu.Label>
            {(tags.data ?? []).map((t) => (
              <Menu.Item key={`a${t.id}`} onClick={() => bulk.mutate({ action: 'add_tag', tag_id: t.id })}>+ {t.name}</Menu.Item>
            ))}
            <Menu.Label>Снять тег</Menu.Label>
            {(tags.data ?? []).map((t) => (
              <Menu.Item key={`r${t.id}`} onClick={() => bulk.mutate({ action: 'remove_tag', tag_id: t.id })}>− {t.name}</Menu.Item>
            ))}
            <Menu.Divider />
            <Menu.Label>Привязать к вакансии</Menu.Label>
            {(vacancies.data ?? []).filter((v) => v.is_active).map((v) => (
              <Menu.Item key={`v${v.id}`} onClick={() => bulk.mutate({ action: 'assign_vacancy', vacancy_id: v.id })}>
                {vacancyLabel(v)}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Group>

      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table highlightOnHover verticalSpacing="xs" miw={900}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={36}>
                <Checkbox checked={allChecked} indeterminate={!allChecked && items.some((c) => selected.includes(c.id))}
                  onChange={() => setSelected(allChecked ? [] : items.map((c) => c.id))} aria-label="Выбрать все" />
              </Table.Th>
              <Table.Th>ФИО</Table.Th>
              <Table.Th>Телефон</Table.Th>
              <Table.Th>Город</Table.Th>
              <Table.Th>Вакансия</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Теги</Table.Th>
              <Table.Th>Добавлен</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((c) => {
              const app = c.applications[0];
              return (
                <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(c.id)}>
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selected.includes(c.id)} aria-label="Выбрать"
                      onChange={() => setSelected(selected.includes(c.id) ? selected.filter((x) => x !== c.id) : [...selected, c.id])} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={500}>{c.full_name}</Text>
                    <Group gap={4}>
                      {c.is_reserve && <Badge size="xs" variant="outline">резерв</Badge>}
                      {c.unsubscribed_at && <Badge size="xs" color="red" variant="outline">отписался</Badge>}
                    </Group>
                  </Table.Td>
                  <Table.Td><Text size="sm" ff="monospace" style={{ whiteSpace: "nowrap" }}>{c.phone_masked}</Text></Table.Td>
                  <Table.Td>{c.city ?? '—'}</Table.Td>
                  <Table.Td>
                    {app ? <Text size="sm">{app.vacancy.title}{c.applications.length > 1 && ` +${c.applications.length - 1}`}</Text>
                      : <Text size="sm" c="dimmed">{c.desired_position ?? '—'}</Text>}
                  </Table.Td>
                  <Table.Td><Badge color={STATUS[c.status].color} variant="light">{STATUS[c.status].label}</Badge></Table.Td>
                  <Table.Td>
                    <Group gap={4}>{c.tags.map((t) => <Badge key={t.id} size="sm" color={t.color} variant="dot">{t.name}</Badge>)}</Group>
                  </Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{dt(c.created_at)}</Text></Table.Td>
                </Table.Tr>
              );
            })}
            {!list.isLoading && items.length === 0 && (
              <Table.Tr><Table.Td colSpan={8}><Text ta="center" c="dimmed" py="lg">Кандидатов не найдено</Text></Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      {(list.data?.total ?? 0) > PAGE_SIZE && (
        <Group justify="center" mt="md">
          <Pagination total={Math.ceil((list.data?.total ?? 0) / PAGE_SIZE)} value={page} onChange={setPage} />
        </Group>
      )}

      <CandidateDrawer id={openId} onClose={() => setOpenId(null)} />
      <ImportWizard opened={importOpen} onClose={() => setImportOpen(false)} />
      <CandidateCreateModal opened={createOpen} onClose={() => setCreateOpen(false)} onCreated={(id) => setOpenId(id)} />
    </>
  );
}
