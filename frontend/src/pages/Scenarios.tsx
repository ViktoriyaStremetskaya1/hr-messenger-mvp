import { Badge, Button, Card, Group, Menu, Paper, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { IconChevronDown, IconPlus } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { api, type LibraryItem, type Scenario } from '../api';
import { useAuth } from '../auth';
import { notifyError } from '../hooks';
import { dt } from '../labels';

export const KINDS: Record<string, string> = {
  offer: 'Предложение вакансии', missed_call: 'Недозвон', screening: 'Скрининг', reminder: 'Напоминание',
  reserve_revival: 'Реанимация резерва', custom: 'Свой',
};

export default function ScenariosPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const editable = can('admin', 'lead');
  const list = useQuery({ queryKey: ['scenarios'], queryFn: () => api<Scenario[]>('/scenarios') });
  const lib = useQuery({ queryKey: ['scenario-library'], queryFn: () => api<LibraryItem[]>('/scenarios/library') });

  const fromLib = useMutation({
    mutationFn: (key: string) => api<Scenario>('/scenarios/from-library', { method: 'POST', json: { key } }),
    onSuccess: (s) => { void qc.invalidateQueries({ queryKey: ['scenarios'] }); nav(`/scenarios/${s.id}`); },
    onError: notifyError,
  });
  const blank = useMutation({
    mutationFn: () => api<Scenario>('/scenarios', { method: 'POST', json: {
      name: 'Новый сценарий', kind: 'custom',
      graph: { start: 'step1', nodes: { step1: { type: 'end', title: 'Завершение', text: { ru: 'Спасибо!', kk: 'Рақмет!' } } } },
    } }),
    onSuccess: (s) => { void qc.invalidateQueries({ queryKey: ['scenarios'] }); nav(`/scenarios/${s.id}`); },
    onError: notifyError,
  });

  const items = list.data ?? [];
  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Сценарии</Title>
        {editable && (
          <Group>
            <Menu position="bottom-end">
              <Menu.Target>
                <Button leftSection={<IconPlus size={16} />} rightSection={<IconChevronDown size={14} />}>Из шаблона</Button>
              </Menu.Target>
              <Menu.Dropdown>
                {(lib.data ?? []).map((l) => <Menu.Item key={l.key} onClick={() => fromLib.mutate(l.key)}>{l.name}</Menu.Item>)}
              </Menu.Dropdown>
            </Menu>
            <Button variant="default" onClick={() => blank.mutate()}>Пустой</Button>
          </Group>
        )}
      </Group>

      {items.length === 0 && !list.isLoading ? (
        <Stack>
          <Text c="dimmed">Сценариев пока нет. Начните с готового шаблона — его можно отредактировать под себя.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {(lib.data ?? []).map((l) => (
              <Card key={l.key} withBorder>
                <Text fw={600}>{l.name}</Text>
                <Text size="sm" c="dimmed" my="xs">{l.description}</Text>
                <Text size="xs" c="dimmed">Шагов: {Object.keys(l.graph.nodes).length}</Text>
                {editable && <Button mt="sm" variant="light" onClick={() => fromLib.mutate(l.key)}>Создать</Button>}
              </Card>
            ))}
          </SimpleGrid>
        </Stack>
      ) : (
        <Paper withBorder style={{ overflowX: 'auto' }}>
          <Table highlightOnHover miw={700}>
            <Table.Thead><Table.Tr><Table.Th>Название</Table.Th><Table.Th>Тип</Table.Th><Table.Th>Шагов</Table.Th>
              <Table.Th>Сейчас в диалогах</Table.Th><Table.Th>Версия</Table.Th><Table.Th>Изменён</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {items.map((s) => (
                <Table.Tr key={s.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/scenarios/${s.id}`)}>
                  <Table.Td fw={500}>{s.name} {!s.is_active && <Badge color="gray" size="xs">выключен</Badge>}</Table.Td>
                  <Table.Td>{KINDS[s.kind] ?? s.kind}</Table.Td>
                  <Table.Td>{Object.keys(s.graph.nodes).length}</Table.Td>
                  <Table.Td>{s.running}</Table.Td>
                  <Table.Td>v{s.version}</Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{dt(s.updated_at)}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
    </>
  );
}
