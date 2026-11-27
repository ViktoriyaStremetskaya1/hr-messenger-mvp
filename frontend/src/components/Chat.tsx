import { Alert, Badge, Box, Button, Group, Paper, ScrollArea, Select, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { IconSend } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api, type ConversationView, type Message, type Template } from '../api';
import { notifyError, useUsers } from '../hooks';
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

export default function Chat({ candidateId, candidateName }: { candidateId: number; candidateName: string }) {
  const qc = useQueryClient();
  const users = useUsers();
  const [text, setText] = useState('');
  const [tplId, setTplId] = useState<string | null>(null);
  const [params, setParams] = useState<string[]>([]);
  const viewport = useRef<HTMLDivElement>(null);

  const conv = useQuery({
    queryKey: ['conversation', candidateId],
    queryFn: () => api<ConversationView>(`/candidates/${candidateId}/conversation`),
    refetchInterval: 3000,
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
          {v.conversation && ` · диалог ведёт: ${v.conversation.mode === 'bot' ? 'бот' : author(v.conversation.assignee_id)}`}
        </Text>
      )}
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
