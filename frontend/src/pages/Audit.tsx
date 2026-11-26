import { Code, Group, Pagination, Paper, Select, Table, Text, TextInput, Title } from '@mantine/core';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, qs, type AuditEntry, type Page } from '../api';
import { useUsers } from '../hooks';
import { dt } from '../labels';

const ACTIONS: Record<string, string> = {
  'auth.login': 'Вход', 'auth.login_failed': 'Неудачный вход', 'user.create': 'Создан пользователь', 'user.update': 'Изменён пользователь',
  'candidate.create': 'Создан кандидат', 'candidate.update': 'Изменён кандидат', 'candidate.phone_reveal': 'Просмотр телефона',
  'candidate.import': 'Импорт', 'application.create': 'Привязка к вакансии', 'application.update': 'Смена статуса',
  'vacancy.create': 'Создана вакансия', 'vacancy.update': 'Изменена вакансия', 'vacancy.delete': 'Удалена вакансия',
  'tag.create': 'Создан тег', 'tag.delete': 'Удалён тег', 'settings.update': 'Изменены настройки',
};

export default function AuditPage() {
  const users = useUsers();
  const [f, setF] = useState({ user_id: null as string | null, action: '' });
  const [page, setPage] = useState(1);
  const params = { ...f, page, page_size: 50 };
  const q = useQuery({ queryKey: ['audit', params], queryFn: () => api<Page<AuditEntry>>(`/audit${qs(params)}`), placeholderData: keepPreviousData });
  const name = (id: number | null) => users.data?.find((u) => u.id === id)?.full_name ?? (id ? `#${id}` : '—');

  return (
    <>
      <Title order={2} mb="md">Журнал действий</Title>
      <Group mb="md">
        <Select placeholder="Пользователь" clearable value={f.user_id} onChange={(v) => { setF({ ...f, user_id: v }); setPage(1); }}
          data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.full_name }))} />
        <TextInput placeholder="Действие (например candidate.)" value={f.action} onChange={(e) => { setF({ ...f, action: e.currentTarget.value }); setPage(1); }} />
      </Group>
      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table miw={800} fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Время</Table.Th><Table.Th>Кто</Table.Th><Table.Th>Действие</Table.Th><Table.Th>Объект</Table.Th><Table.Th>Детали</Table.Th><Table.Th>IP</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(q.data?.items ?? []).map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td>{dt(e.created_at)}</Table.Td>
                <Table.Td>{name(e.user_id)}</Table.Td>
                <Table.Td>{ACTIONS[e.action] ?? e.action}</Table.Td>
                <Table.Td>{e.entity ? `${e.entity} #${e.entity_id}` : '—'}</Table.Td>
                <Table.Td maw={360}>{Object.keys(e.diff).length ? <Code block fz="xs">{JSON.stringify(e.diff, null, 1)}</Code> : '—'}</Table.Td>
                <Table.Td><Text size="xs">{e.ip}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      {(q.data?.total ?? 0) > 50 && (
        <Group justify="center" mt="md"><Pagination total={Math.ceil((q.data?.total ?? 0) / 50)} value={page} onChange={setPage} /></Group>
      )}
    </>
  );
}
