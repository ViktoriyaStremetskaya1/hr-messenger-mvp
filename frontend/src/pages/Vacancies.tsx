import { ActionIcon, Badge, Button, Group, Modal, NumberInput, Paper, SegmentedControl, SimpleGrid, Stack, Switch, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type FaqItem, type Vacancy } from '../api';
import { useAuth } from '../auth';
import { notifyError, notifyOk, useVacancies } from '../hooks';
import { money } from '../labels';

type Form = Omit<Vacancy, 'id' | 'candidates_count'>;
const EMPTY: Form = { title: '', city: '', schedule: '', salary_from: null, salary_to: null, requirements: '', office_address: '',
  description: '', faq: [], is_active: true };

export default function VacanciesPage() {
  const vacancies = useVacancies();
  const [filter, setFilter] = useState('active');
  const [edit, setEdit] = useState<{ id: number | null; form: Form } | null>(null);
  const list = (vacancies.data ?? []).filter((v) => filter === 'all' || v.is_active === (filter === 'active'));

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Вакансии</Title>
        <Group>
          <SegmentedControl value={filter} onChange={setFilter}
            data={[{ value: 'active', label: 'Активные' }, { value: 'archive', label: 'Архив' }, { value: 'all', label: 'Все' }]} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ id: null, form: EMPTY })}>Новая вакансия</Button>
        </Group>
      </Group>
      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table highlightOnHover miw={800}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Должность</Table.Th><Table.Th>Город</Table.Th><Table.Th>График</Table.Th>
              <Table.Th>Зарплата</Table.Th><Table.Th>Кандидатов</Table.Th><Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {list.map((v) => (
              <Table.Tr key={v.id} style={{ cursor: 'pointer' }} onClick={() => {
                const { id, candidates_count, ...form } = v;
                void candidates_count;
                setEdit({ id, form });
              }}>
                <Table.Td fw={500}>{v.title}</Table.Td>
                <Table.Td>{v.city}</Table.Td>
                <Table.Td>{v.schedule || '—'}</Table.Td>
                <Table.Td>{money(v.salary_from, v.salary_to)}</Table.Td>
                <Table.Td>{v.candidates_count}</Table.Td>
                <Table.Td>{!v.is_active && <Badge color="gray">архив</Badge>}</Table.Td>
              </Table.Tr>
            ))}
            {!vacancies.isLoading && list.length === 0 && (
              <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Вакансий нет</Text></Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      {edit && <VacancyModal id={edit.id} initial={edit.form} onClose={() => setEdit(null)} />}
    </>
  );
}

function VacancyModal({ id, initial, onClose }: { id: number | null; initial: Form; onClose: () => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [f, setF] = useState<Form>(initial);
  const set = (patch: Partial<Form>) => setF({ ...f, ...patch });
  const done = (msg: string) => { notifyOk(msg); void qc.invalidateQueries({ queryKey: ['vacancies'] }); onClose(); };

  const save = useMutation({
    mutationFn: () => api<Vacancy>(id ? `/vacancies/${id}` : '/vacancies', { method: id ? 'PUT' : 'POST', json: {
      ...f, faq: f.faq.filter((x) => x.q.trim() && x.a.trim()) } }),
    onSuccess: () => done('Вакансия сохранена'),
    onError: notifyError,
  });
  const remove = useMutation({
    mutationFn: () => api(`/vacancies/${id}`, { method: 'DELETE' }),
    onSuccess: () => done('Вакансия удалена'),
    onError: notifyError,
  });
  const setFaq = (i: number, patch: Partial<FaqItem>) => set({ faq: f.faq.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  return (
    <Modal opened onClose={onClose} title={id ? 'Вакансия' : 'Новая вакансия'} size="lg">
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label="Должность" required value={f.title} onChange={(e) => set({ title: e.currentTarget.value })} />
          <TextInput label="Город" required value={f.city} onChange={(e) => set({ city: e.currentTarget.value })} />
          <TextInput label="График" placeholder="5/2, 09:00–18:00" value={f.schedule ?? ''} onChange={(e) => set({ schedule: e.currentTarget.value })} />
          <Group grow>
            <NumberInput label="Зарплата от, ₸" thousandSeparator=" " min={0} value={f.salary_from ?? ''}
              onChange={(v) => set({ salary_from: v === '' ? null : Number(v) })} />
            <NumberInput label="до, ₸" thousandSeparator=" " min={0} value={f.salary_to ?? ''}
              onChange={(v) => set({ salary_to: v === '' ? null : Number(v) })} />
          </Group>
        </SimpleGrid>
        <TextInput label="Адрес офиса" value={f.office_address ?? ''} onChange={(e) => set({ office_address: e.currentTarget.value })} />
        <Textarea label="Требования" autosize minRows={2} value={f.requirements ?? ''} onChange={(e) => set({ requirements: e.currentTarget.value })} />
        <Textarea label="Описание" autosize minRows={2} value={f.description ?? ''} onChange={(e) => set({ description: e.currentTarget.value })} />
        <div>
          <Text size="sm" fw={500}>Частые вопросы</Text>
          <Text size="xs" c="dimmed" mb="xs">Бот и ИИ отвечают кандидатам только по данным карточки и этим ответам</Text>
          <Stack gap="xs">
            {f.faq.map((x, i) => (
              <Group key={i} align="flex-start" wrap="nowrap">
                <TextInput style={{ flex: 1 }} placeholder="Вопрос" value={x.q} onChange={(e) => setFaq(i, { q: e.currentTarget.value })} />
                <Textarea style={{ flex: 2 }} autosize placeholder="Ответ" value={x.a} onChange={(e) => setFaq(i, { a: e.currentTarget.value })} />
                <ActionIcon variant="subtle" color="red" mt={6} onClick={() => set({ faq: f.faq.filter((_, j) => j !== i) })} aria-label="Удалить">
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            ))}
            <Button variant="light" size="xs" w="fit-content" onClick={() => set({ faq: [...f.faq, { q: '', a: '' }] })}>+ Вопрос</Button>
          </Stack>
        </div>
        <Switch label="Активна (в архиве — не видна в рассылках)" checked={f.is_active} onChange={(e) => set({ is_active: e.currentTarget.checked })} />
        <Group justify="space-between">
          {id && can('admin', 'lead') ? (
            <Button color="red" variant="subtle" loading={remove.isPending}
              onClick={() => window.confirm('Удалить вакансию?') && remove.mutate()}>Удалить</Button>
          ) : <span />}
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!f.title || !f.city}>Сохранить</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
