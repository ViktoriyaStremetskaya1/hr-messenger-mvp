import { ActionIcon, Badge, Button, Chip, Group, NumberInput, Paper, Select, Stack, Switch, Text, TextInput, Title } from '@mantine/core';
import { IconX } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import { notifyError, notifyOk, useTags } from '../hooks';
import { TAG_COLORS } from '../labels';

interface Settings {
  working_hours: { start: string; end: string; days: number[] };
  touch_frequency_days: number;
  rate_limit_per_minute: number;
  daily_send_limit: number;
  stop_words: string[];
  feature_flags: { ai: boolean };
}
const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

export default function SettingsPage() {
  const { can } = useAuth();
  const editable = can('admin', 'lead');
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/settings') });
  const [s, setS] = useState<Settings | null>(null);
  useEffect(() => { if (q.data) setS(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<Settings>('/settings', { method: 'PATCH', json: s }),
    onSuccess: (d) => { qc.setQueryData(['settings'], d); notifyOk('Настройки сохранены'); },
    onError: notifyError,
  });

  return (
    <Stack maw={720}>
      <Title order={2}>Настройки</Title>
      {s && (
        <Paper withBorder p="md">
          <Stack>
            <Title order={4}>Правила рассылок</Title>
            <Text size="sm" c="dimmed">Время — Asia/Almaty (UTC+5). Сообщения вне рабочих часов откладываются до начала следующего окна.</Text>
            <Group>
              <TextInput label="С" type="time" value={s.working_hours.start} disabled={!editable}
                onChange={(e) => setS({ ...s, working_hours: { ...s.working_hours, start: e.currentTarget.value } })} />
              <TextInput label="До" type="time" value={s.working_hours.end} disabled={!editable}
                onChange={(e) => setS({ ...s, working_hours: { ...s.working_hours, end: e.currentTarget.value } })} />
            </Group>
            <Chip.Group multiple value={s.working_hours.days.map(String)}
              onChange={(v) => setS({ ...s, working_hours: { ...s.working_hours, days: v.map(Number).sort() } })}>
              <Group gap={6}>{DAYS.map((d, i) => <Chip key={d} value={String(i + 1)} disabled={!editable}>{d}</Chip>)}</Group>
            </Chip.Group>
            <Group grow>
              <NumberInput label="Не чаще 1 касания в N дней" min={0} value={s.touch_frequency_days} disabled={!editable}
                onChange={(v) => setS({ ...s, touch_frequency_days: Number(v) || 0 })} />
              <NumberInput label="Отправок в минуту" min={1} value={s.rate_limit_per_minute} disabled={!editable}
                onChange={(v) => setS({ ...s, rate_limit_per_minute: Number(v) || 1 })} />
              <NumberInput label="Отправок в сутки" min={1} value={s.daily_send_limit} disabled={!editable}
                onChange={(v) => setS({ ...s, daily_send_limit: Number(v) || 1 })} />
            </Group>
            <TextInput label="Стоп-слова (через запятую)" description="Кандидат, написавший любое из них, сразу исключается из рассылок"
              value={s.stop_words.join(', ')} disabled={!editable}
              onChange={(e) => setS({ ...s, stop_words: e.currentTarget.value.split(',').map((x) => x.trim()).filter(Boolean) })} />
            <Switch label="ИИ-ассистент (этап 8)" checked={s.feature_flags.ai} disabled={!editable}
              onChange={(e) => setS({ ...s, feature_flags: { ...s.feature_flags, ai: e.currentTarget.checked } })} />
            {editable && <Group justify="flex-end"><Button loading={save.isPending} onClick={() => save.mutate()}>Сохранить</Button></Group>}
          </Stack>
        </Paper>
      )}
      <TagsBlock />
    </Stack>
  );
}

function TagsBlock() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const tags = useTags();
  const [name, setName] = useState('');
  const [color, setColor] = useState<string | null>('gray');
  const refresh = () => void qc.invalidateQueries({ queryKey: ['tags'] });
  const create = useMutation({
    mutationFn: () => api('/tags', { method: 'POST', json: { name, color } }),
    onSuccess: () => { setName(''); refresh(); },
    onError: notifyError,
  });
  const remove = useMutation({ mutationFn: (id: number) => api(`/tags/${id}`, { method: 'DELETE' }), onSuccess: refresh, onError: notifyError });
  return (
    <Paper withBorder p="md">
      <Stack>
        <Title order={4}>Теги</Title>
        <Group gap="xs">
          {(tags.data ?? []).map((t) => (
            <Badge key={t.id} color={t.color} variant="light" size="lg"
              rightSection={can('admin', 'lead') && (
                <ActionIcon size="xs" variant="transparent" color={t.color} aria-label="Удалить"
                  onClick={() => window.confirm(`Удалить тег «${t.name}»?`) && remove.mutate(t.id)}><IconX size={12} /></ActionIcon>
              )}>{t.name}</Badge>
          ))}
        </Group>
        <Group align="flex-end">
          <TextInput label="Новый тег" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Select label="Цвет" data={TAG_COLORS} value={color} onChange={setColor} w={120} />
          <Button variant="light" disabled={!name.trim()} onClick={() => create.mutate()}>Добавить</Button>
        </Group>
      </Stack>
    </Paper>
  );
}
