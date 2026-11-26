import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  Loader,
  MultiSelect,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { IconEye } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, type Application, type Candidate } from '../api';
import { notifyError, notifyOk, useTags, useUsers, vacancyLabel, useVacancies } from '../hooks';
import { dt, screeningOptions, statusOptions } from '../labels';

export default function CandidateDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const qc = useQueryClient();
  const tags = useTags();
  const vacancies = useVacancies();
  const users = useUsers();
  const [phone, setPhone] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<Candidate> & { tag_ids?: string[] }>({});
  const [addVac, setAddVac] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ['candidate', id],
    queryFn: () => api<Candidate>(`/candidates/${id}`),
    enabled: id !== null,
  });
  const c = q.data;

  useEffect(() => {
    setPhone(null);
    if (c) setForm({ full_name: c.full_name, city: c.city, source: c.source, notes: c.notes, language: c.language,
      is_reserve: c.is_reserve, owner_id: c.owner_id, tag_ids: c.tags.map((t) => String(t.id)) });
  }, [c]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['candidates'] });
    void qc.invalidateQueries({ queryKey: ['candidate', id] });
  };

  const save = useMutation({
    mutationFn: () => api<Candidate>(`/candidates/${id}`, { method: 'PATCH', json: {
      ...form, tag_ids: (form.tag_ids ?? []).map(Number) } }),
    onSuccess: () => { notifyOk('Сохранено'); refresh(); },
    onError: notifyError,
  });
  const updateApp = useMutation({
    mutationFn: ({ appId, patch }: { appId: number; patch: Partial<Application> }) =>
      api(`/candidates/applications/${appId}`, { method: 'PATCH', json: patch }),
    onSuccess: refresh,
    onError: notifyError,
  });
  const addApp = useMutation({
    mutationFn: () => api(`/candidates/${id}/applications`, { method: 'POST', json: { vacancy_id: Number(addVac) } }),
    onSuccess: () => { setAddVac(null); refresh(); },
    onError: notifyError,
  });

  const reveal = async () => {
    try {
      setPhone((await api<{ phone: string }>(`/candidates/${id}/phone`)).phone);
    } catch (e) { notifyError(e); }
  };

  const userOptions = (users.data ?? []).filter((u) => u.is_active).map((u) => ({ value: String(u.id), label: u.full_name }));
  const linked = new Set(c?.applications.map((a) => a.vacancy.id));

  return (
    <Drawer opened={id !== null} onClose={onClose} position="right" size="lg" title={c?.full_name ?? 'Кандидат'}>
      {!c ? <Loader /> : (
        <Stack>
          {c.unsubscribed_at && <Alert color="red">Отписался от рассылок {dt(c.unsubscribed_at)}</Alert>}
          <Group>
            <Text ff="monospace">{phone ?? c.phone_masked}</Text>
            {!phone && <Button size="xs" variant="subtle" leftSection={<IconEye size={14} />} onClick={reveal}>Показать номер</Button>}
          </Group>
          <Text size="xs" c="dimmed">Показ номера записывается в журнал действий</Text>

          <TextInput label="ФИО" value={form.full_name ?? ''} onChange={(e) => setForm({ ...form, full_name: e.currentTarget.value })} />
          <Group grow>
            <TextInput label="Город" value={form.city ?? ''} onChange={(e) => setForm({ ...form, city: e.currentTarget.value || null })} />
            <TextInput label="Источник" value={form.source ?? ''} onChange={(e) => setForm({ ...form, source: e.currentTarget.value || null })} />
          </Group>
          <Group grow>
            <Select label="Язык общения" data={[{ value: 'ru', label: 'Русский' }, { value: 'kk', label: 'Қазақша' }]}
              value={form.language ?? null} onChange={(v) => setForm({ ...form, language: v as Candidate['language'] })} clearable />
            <Select label="Ответственный" data={userOptions} value={form.owner_id ? String(form.owner_id) : null}
              onChange={(v) => setForm({ ...form, owner_id: v ? Number(v) : null })} clearable />
          </Group>
          <MultiSelect label="Теги" data={(tags.data ?? []).map((t) => ({ value: String(t.id), label: t.name }))}
            value={form.tag_ids ?? []} onChange={(v) => setForm({ ...form, tag_ids: v })} />
          <Switch label="Кадровый резерв" checked={!!form.is_reserve} onChange={(e) => setForm({ ...form, is_reserve: e.currentTarget.checked })} />
          <Textarea label="Заметки" autosize minRows={2} value={form.notes ?? ''} onChange={(e) => setForm({ ...form, notes: e.currentTarget.value || null })} />
          {c.desired_position && <Text size="sm" c="dimmed">Желаемая должность из импорта: {c.desired_position}</Text>}
          <Group justify="flex-end"><Button onClick={() => save.mutate()} loading={save.isPending}>Сохранить</Button></Group>

          <Divider label="Вакансии и статусы" />
          {c.applications.length === 0 && <Text size="sm" c="dimmed">Не привязан ни к одной вакансии</Text>}
          {c.applications.map((a) => (
            <Card key={a.id} withBorder padding="sm">
              <Group justify="space-between" mb="xs">
                <Text fw={500}>{vacancyLabel(a.vacancy)}</Text>
                <Text size="xs" c="dimmed">обновлено {dt(a.updated_at)}</Text>
              </Group>
              <Group grow>
                <Select label="Статус" data={statusOptions} value={a.status}
                  onChange={(v) => v && updateApp.mutate({ appId: a.id, patch: { status: v as Application['status'] } })} />
                <Select label="Скрининг" data={screeningOptions} value={a.screening_result} clearable
                  onChange={(v) => updateApp.mutate({ appId: a.id, patch: { screening_result: v as Application['screening_result'] } })} />
              </Group>
            </Card>
          ))}
          <Group align="flex-end">
            <Select style={{ flex: 1 }} placeholder="Привязать к вакансии" searchable value={addVac} onChange={setAddVac}
              data={(vacancies.data ?? []).filter((v) => v.is_active && !linked.has(v.id)).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
            <Button variant="light" disabled={!addVac} onClick={() => addApp.mutate()} loading={addApp.isPending}>Добавить</Button>
          </Group>
          <Group gap="xs"><Badge variant="light">создан {dt(c.created_at)}</Badge>
            {c.last_touch_at && <Badge variant="light">последнее касание {dt(c.last_touch_at)}</Badge>}</Group>
        </Stack>
      )}
    </Drawer>
  );
}
