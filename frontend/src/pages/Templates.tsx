import { Alert, Badge, Button, Group, Modal, Paper, SegmentedControl, Select, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { IconPlus, IconRefresh } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type ChannelStatus, type Template } from '../api';
import { useAuth } from '../auth';
import { notifyError, notifyOk } from '../hooks';

const STATUS: Record<string, { label: string; color: string }> = {
  APPROVED: { label: 'Одобрен', color: 'green' },
  PENDING: { label: 'На проверке', color: 'yellow' },
  REJECTED: { label: 'Отклонён', color: 'red' },
  LOCAL: { label: 'Черновик', color: 'gray' },
};

export default function TemplatesPage() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const editable = can('admin', 'lead');
  const [lang, setLang] = useState('all');
  const [edit, setEdit] = useState<Template | 'new' | null>(null);
  const q = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') });
  const ch = useQuery({ queryKey: ['channel'], queryFn: () => api<ChannelStatus>('/channel/status') });
  const sync = useMutation({
    mutationFn: () => api<{ created: number; updated: number; total: number }>('/templates/sync', { method: 'POST' }),
    onSuccess: (r) => { notifyOk(`Получено из Meta: ${r.total}. Новых: ${r.created}, обновлено: ${r.updated}`); void qc.invalidateQueries({ queryKey: ['templates'] }); },
    onError: notifyError,
  });
  const list = (q.data ?? []).filter((t) => lang === 'all' || t.language === lang);

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Шаблоны WhatsApp</Title>
        <Group>
          <SegmentedControl value={lang} onChange={setLang} data={[{ value: 'all', label: 'Все' }, { value: 'ru', label: 'Рус' }, { value: 'kk', label: 'Қаз' }]} />
          {editable && <Button variant="default" leftSection={<IconRefresh size={16} />} loading={sync.isPending} onClick={() => sync.mutate()}>Синхронизировать с Meta</Button>}
          {editable && <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit('new')}>Черновик</Button>}
        </Group>
      </Group>
      <Alert mb="md" color={ch.data?.mode === 'mock' ? 'blue' : 'teal'}>
        {ch.data?.mode === 'mock'
          ? 'Режим песочницы: шаблоны и отправка идут в мок WhatsApp. Реальные сообщения не уходят.'
          : `Боевой режим${ch.data?.display_phone ? `, номер ${ch.data.display_phone}` : ''}. Шаблоны создаются и проходят проверку в WhatsApp Manager, здесь — «Синхронизировать».`}
        {' '}Первое сообщение кандидату и любое сообщение вне 24-часового окна — только одобренным шаблоном.
      </Alert>
      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table miw={800} verticalSpacing="sm">
          <Table.Thead><Table.Tr><Table.Th>Имя</Table.Th><Table.Th>Язык</Table.Th><Table.Th>Категория</Table.Th><Table.Th>Текст</Table.Th><Table.Th>Статус</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {list.map((t) => (
              <Table.Tr key={t.id} style={{ cursor: t.status === 'LOCAL' && editable ? 'pointer' : undefined }}
                onClick={() => t.status === 'LOCAL' && editable && setEdit(t)}>
                <Table.Td ff="monospace" fz="sm">{t.name}</Table.Td>
                <Table.Td>{t.language === 'ru' ? 'Русский' : 'Қазақша'}</Table.Td>
                <Table.Td><Text size="xs">{t.category === 'UTILITY' ? 'Служебный' : 'Маркетинг'}</Text></Table.Td>
                <Table.Td maw={420}>
                  <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{t.body}</Text>
                  {t.buttons.length > 0 && <Group gap={4} mt={4}>{t.buttons.map((b, i) => <Badge key={i} size="xs" variant="outline" tt="none">{b.text}</Badge>)}</Group>}
                </Table.Td>
                <Table.Td><Badge color={STATUS[t.status]?.color ?? 'gray'} variant="light">{STATUS[t.status]?.label ?? t.status}</Badge></Table.Td>
              </Table.Tr>
            ))}
            {!q.isLoading && list.length === 0 && (
              <Table.Tr><Table.Td colSpan={5}><Text ta="center" c="dimmed" py="lg">Шаблонов нет — нажмите «Синхронизировать с Meta»</Text></Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Paper>
      {edit && <DraftModal tpl={edit === 'new' ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function DraftModal({ tpl, onClose }: { tpl: Template | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: tpl?.name ?? '', language: tpl?.language ?? 'ru', category: tpl?.category ?? 'MARKETING',
    body: tpl?.body ?? '', buttons: (tpl?.buttons ?? []).map((b) => b.text ?? '').join('\n') });
  const done = () => { void qc.invalidateQueries({ queryKey: ['templates'] }); onClose(); };
  const json = () => ({ name: f.name, language: f.language, category: f.category, body: f.body,
    buttons: f.buttons.split('\n').map((x) => x.trim()).filter(Boolean).slice(0, 3).map((text) => ({ type: 'QUICK_REPLY', text })) });
  const save = useMutation({
    mutationFn: () => api(tpl ? `/templates/${tpl.id}` : '/templates', { method: tpl ? 'PUT' : 'POST', json: json() }),
    onSuccess: done, onError: notifyError,
  });
  const remove = useMutation({ mutationFn: () => api(`/templates/${tpl!.id}`, { method: 'DELETE' }), onSuccess: done, onError: notifyError });
  return (
    <Modal opened onClose={onClose} title={tpl ? 'Черновик шаблона' : 'Новый черновик'} size="lg">
      <Stack>
        <Text size="sm" c="dimmed">Черновик — заготовка текста. Чтобы отправлять, создайте шаблон с тем же именем в WhatsApp Manager, дождитесь одобрения и синхронизируйте.</Text>
        <Group grow>
          <TextInput label="Имя (латиница, цифры, _)" value={f.name} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
          <Select label="Язык" data={[{ value: 'ru', label: 'Русский' }, { value: 'kk', label: 'Қазақша' }]} value={f.language}
            onChange={(v) => v && setF({ ...f, language: v as 'ru' | 'kk' })} />
          <Select label="Категория" data={[{ value: 'MARKETING', label: 'Маркетинг' }, { value: 'UTILITY', label: 'Служебный' }]} value={f.category}
            onChange={(v) => v && setF({ ...f, category: v as 'MARKETING' | 'UTILITY' })} />
        </Group>
        <Textarea label="Текст" description="Переменные: {{1}}, {{2}}…" autosize minRows={3} value={f.body} onChange={(e) => setF({ ...f, body: e.currentTarget.value })} />
        <Textarea label="Кнопки быстрого ответа" description="По одной в строке, до 3" autosize minRows={2} value={f.buttons}
          onChange={(e) => setF({ ...f, buttons: e.currentTarget.value })} />
        <Group justify="space-between">
          {tpl ? <Button color="red" variant="subtle" onClick={() => remove.mutate()}>Удалить</Button> : <span />}
          <Button loading={save.isPending} onClick={() => save.mutate()} disabled={!f.name || !f.body}>Сохранить</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
