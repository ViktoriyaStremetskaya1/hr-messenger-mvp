import { Alert, Badge, Box, Button, Group, Paper, ScrollArea, Select, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { IconSend } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api, type ConversationView, type Message, type Scenario, type Template } from '../api';
import { notifyError, notifyOk, useUsers, useVacancies, vacancyLabel } from '../hooks';
import { dt } from '../labels';

const TICKS: Record<Message['status'], string> = {
  queued: '🕓', sent: '✓', delivered: '✓✓', read: '✓✓ прочитано', failed: '⚠', received: '',
};

function Bubble({ m, author }: { m: Message; author: string }) {
  const out = m.direction === 'out';
  const buttons = (m.payload.buttons ?? []).map((b) => b.text ?? b.title).filter(Boolean) as string[];
  const outButtons = m.payload.out?.buttons?.map((b) => b.title) ?? m.payload.out?.rows?.map((r) => r.title) ?? [];
  const all = buttons.length ? buttons : outButtons;
  return (
    <Box style={{ alignSelf: out ? 'flex-end' : 'flex-start', maxWidth: '80%' }}>
      <Paper p="xs" radius="md" withBorder
        bg={out ? (m.status === 'failed' ? 'var(--mantine-color-red-light)' : 'var(--mantine-color-teal-light)') : 'var(--mantine-color-default)'}>
        {m.type === 'template' && <Badge size="xs" variant="light" mb={4}>шаблон</Badge>}
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{m.body}</Text>
        {all.length > 0 && (
          <Group gap={4} mt={6}>{all.map((b) => <Badge key={b} variant="outline" size="sm" tt="none">{b}</Badge>)}</Group>
        )}
        {m.error && <Text size="xs" c="red" mt={4}>{m.error}</Text>}
      </Paper>
      <Text size="xs" c="dimmed" ta={out ? 'right' : 'left'} mt={2}>
        {out ? `${author} · ` : ''}{dt(m.created_at)} {out ? TICKS[m.status] : ''}
      </Text>
    </Box>
  );
}

const OUTCOME: Record<string, string> = {
  completed: 'завершён', handoff: 'передан рекрутеру', no_reply: 'кандидат не ответил', stopped: 'остановлен',
  unsubscribed: 'кандидат отписался', error: 'ошибка',
};

function ScenarioPanel({ candidateId, view, defaultVacancyId }: { candidateId: number; view: ConversationView; defaultVacancyId: number | null }) {
  const qc = useQueryClient();
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: () => api<Scenario[]>('/scenarios') });
  const vacancies = useVacancies();
  const [sid, setSid] = useState<string | null>(null);
  const [vid, setVid] = useState<string | null>(defaultVacancyId ? String(defaultVacancyId) : null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ['conversation', candidateId] });
  const call = useMutation({
    mutationFn: ({ method, path, json }: { method: string; path: string; json?: object }) => api(path, { method, json }),
    onSuccess: (_, v) => { refresh(); if (v.method === 'POST' && v.path.endsWith('/scenario')) notifyOk('Сценарий запущен'); },
    onError: notifyError,
  });
  const st = view.scenario;
  const active = !!st?.current_node;
  const options = (scenarios.data ?? []).filter((s) => s.is_active && s.kind !== 'reminder').map((s) => ({ value: String(s.id), label: s.name }));

  if (view.unsubscribed) return null;
  return (
    <Paper withBorder p="xs">
      {active ? (
        <Group justify="space-between" gap="xs">
          <Text size="xs">
            🤖 <b>{st!.scenario_name}</b> · шаг «{st!.current_title ?? st!.current_node}» {st!.waiting ? '· ждём ответа' : ''}
            {view.conversation?.mode === 'human' && <Badge ml={6} size="xs" color="orange">бот на паузе</Badge>}
          </Text>
          <Group gap={4}>
            {view.conversation?.mode === 'human' && (
              <Button size="compact-xs" variant="light" onClick={() => call.mutate({ method: 'POST', path: `/candidates/${candidateId}/bot` })}>Вернуть боту</Button>
            )}
            <Button size="compact-xs" color="red" variant="subtle" onClick={() => call.mutate({ method: 'DELETE', path: `/candidates/${candidateId}/scenario` })}>Остановить</Button>
          </Group>
        </Group>
      ) : (
        <Stack gap={6}>
          {st && (
            <Text size="xs" c="dimmed">
              Последний сценарий «{st.scenario_name}»: {OUTCOME[st.outcome ?? ''] ?? st.outcome}{st.reason ? ` — ${st.reason}` : ''}
            </Text>
          )}
          <Group gap={6} wrap="nowrap" align="flex-end">
            <Select size="xs" style={{ flex: 1 }} placeholder="Запустить сценарий…" data={options} value={sid} onChange={setSid} />
            <Select size="xs" style={{ flex: 1 }} placeholder="Вакансия" searchable clearable value={vid} onChange={setVid}
              data={(vacancies.data ?? []).filter((v) => v.is_active).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
            <Button size="xs" disabled={!sid} loading={call.isPending}
              onClick={() => call.mutate({ method: 'POST', path: `/candidates/${candidateId}/scenario`, json: { scenario_id: Number(sid), vacancy_id: vid ? Number(vid) : null } })}>
              Запустить
            </Button>
          </Group>
        </Stack>
      )}
      {st && Object.keys(st.answers).length > 0 && (
        <Group gap={4} mt={6}>
          {Object.entries(st.answers).map(([k, v]) => <Badge key={k} size="xs" variant="outline" tt="none">{k}: {v}</Badge>)}
        </Group>
      )}
    </Paper>
  );
}

export default function Chat({ candidateId, candidateName, defaultVacancyId = null }: { candidateId: number; candidateName: string; defaultVacancyId?: number | null }) {
  const qc = useQueryClient();
  const users = useUsers();
  const [text, setText] = useState('');
  const [tplId, setTplId] = useState<string | null>(null);
  const [params, setParams] = useState<string[]>([]);
  const viewport = useRef<HTMLDivElement>(null);

  const conv = useQuery({
    queryKey: ['conversation', candidateId],
    queryFn: () => api<ConversationView>(`/candidates/${candidateId}/conversation`),
    refetchInterval: 15_000, // основное обновление — через события сервера (SSE)
  });
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') });
  const approved = (templates.data ?? []).filter((t) => t.status === 'APPROVED');
  const tpl = approved.find((t) => String(t.id) === tplId);

  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight });
  }, [conv.data?.messages.length]);

  const send = useMutation({
    mutationFn: (body: object) => api(`/candidates/${candidateId}/messages`, { method: 'POST', json: body }),
    onSuccess: () => {
      setText('');
      setTplId(null);
      setParams([]);
      void qc.invalidateQueries({ queryKey: ['conversation', candidateId] });
    },
    onError: notifyError,
  });

  const v = conv.data;
  const author = (id: number | null) => (id ? users.data?.find((u) => u.id === id)?.full_name ?? 'Рекрутер' : 'Бот');
  const preview = tpl ? tpl.body.replace(/\{\{(\d+)\}\}/g, (_, n) => params[Number(n) - 1] || `{{${n}}}`) : '';

  return (
    <Stack gap="xs">
      {v?.unsubscribed && <Alert color="red" py={6}>Кандидат отписался — отправка недоступна</Alert>}
      {v && !v.unsubscribed && (
        <Text size="xs" c={v.window_open ? 'teal' : 'orange'}>
          {v.window_open
            ? `Окно 24 ч открыто до ${dt(v.window_expires_at)} — можно писать свободно`
            : 'Окно 24 ч закрыто — первым сообщением можно отправить только одобренный шаблон'}
          {v.conversation && (v.conversation.mode === 'bot' && v.scenario?.current_node
            ? ' · диалог ведёт бот'
            : ` · ответственный: ${v.conversation.assignee_id ? author(v.conversation.assignee_id) : 'не назначен'}`)}
        </Text>
      )}
      {v && <ScenarioPanel candidateId={candidateId} view={v} defaultVacancyId={defaultVacancyId} />}
      <ScrollArea h={360} viewportRef={viewport} type="auto">
        <Stack gap={8} p={4}>
          {v?.messages.map((m) => <Bubble key={m.id} m={m} author={author(m.sent_by_user_id)} />)}
          {v && v.messages.length === 0 && <Text c="dimmed" size="sm" ta="center" py="xl">Переписки пока нет</Text>}
        </Stack>
      </ScrollArea>

      {v && !v.unsubscribed && (v.window_open ? (
        <Group align="flex-end" wrap="nowrap">
          <Textarea style={{ flex: 1 }} autosize minRows={1} maxRows={5} placeholder={`Сообщение для ${candidateName}`} value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && text.trim()) { e.preventDefault(); send.mutate({ kind: 'text', text }); } }} />
          <Button onClick={() => send.mutate({ kind: 'text', text })} disabled={!text.trim()} loading={send.isPending} aria-label="Отправить">
            <IconSend size={16} />
          </Button>
        </Group>
      ) : null)}
      {v && !v.unsubscribed && (
        <Paper withBorder p="xs">
          <Stack gap="xs">
            <Select size="xs" placeholder={approved.length ? 'Отправить шаблон…' : 'Нет одобренных шаблонов — синхронизируйте на странице «Шаблоны»'}
              data={approved.map((t) => ({ value: String(t.id), label: `${t.name} · ${t.language}` }))} value={tplId} clearable
              onChange={(id) => { setTplId(id); const t = approved.find((x) => String(x.id) === id); setParams(Array(t?.params_count ?? 0).fill('')); }} />
            {tpl && (
              <>
                {params.map((p, i) => (
                  <TextInput key={i} size="xs" label={`Параметр {{${i + 1}}}`} value={p}
                    onChange={(e) => setParams(params.map((x, j) => (j === i ? e.currentTarget.value : x)))} />
                ))}
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>{preview}</Text>
                <Group justify="flex-end">
                  <Button size="xs" loading={send.isPending} disabled={params.some((p) => !p.trim())}
                    onClick={() => send.mutate({ kind: 'template', template_id: tpl.id, params })}>Отправить шаблон</Button>
                </Group>
              </>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
