import {
  ActionIcon, Alert, Badge, Button, Card, Grid, Group, JsonInput, Menu, NumberInput, Paper, ScrollArea, Select, Stack,
  Switch, Tabs, Text, Textarea, TextInput, Title, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconArrowLeft, IconFlag, IconPlus, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api, ApiError, type Scenario, type ScenarioGraph, type ScenarioNode, type ScenarioOption, type ScenarioRule, type Template, type Texts } from '../api';
import { useAuth } from '../auth';
import { notifyError, notifyOk } from '../hooks';
import { screeningOptions, statusOptions } from '../labels';
import { KINDS } from './Scenarios';

export const NODE_TYPES: Record<string, { label: string; color: string; hint: string }> = {
  template: { label: 'Шаблон WhatsApp', color: 'green', hint: 'Одобренный шаблон с кнопками. Только им можно начать диалог вне 24-часового окна.' },
  message: { label: 'Сообщение', color: 'gray', hint: 'Просто текст, дальше — следующий шаг.' },
  buttons: { label: 'Вопрос с кнопками', color: 'blue', hint: 'До 3 вариантов — кнопками, до 10 — списком.' },
  question: { label: 'Свободный ответ', color: 'cyan', hint: 'Кандидат отвечает текстом; ответ сохраняется в переменную.' },
  language: { label: 'Выбор языка', color: 'grape', hint: 'Русский / Қазақша. Пропускается, если язык уже известен.' },
  vacancy_choice: { label: 'Выбор вакансии', color: 'indigo', hint: 'Список активных вакансий в городе кандидата.' },
  condition: { label: 'Условие', color: 'orange', hint: 'Ветвление по ответам кандидата.' },
  set: { label: 'Результат / статус', color: 'yellow', hint: 'Проставить результат скрининга, статус, резерв.' },
  booking: { label: 'Запись на собеседование', color: 'violet', hint: 'Выбор слота появится на этапе 5; пока — передача рекрутеру.' },
  handoff: { label: 'Передать рекрутеру', color: 'red', hint: 'Бот прекращает отвечать, диалог переходит к рекрутеру.' },
  end: { label: 'Завершение', color: 'dark', hint: 'Сценарий закончен.' },
};
const WITH_TEXT = new Set(['message', 'buttons', 'question', 'vacancy_choice', 'booking', 'handoff', 'end']);
const WITH_NEXT = new Set(['message', 'question', 'language', 'set', 'vacancy_choice']);
const WAITING = new Set(['template', 'buttons', 'question', 'language', 'vacancy_choice']);
const OPS = [
  { value: 'eq', label: 'равно' }, { value: 'neq', label: 'не равно' }, { value: 'in', label: 'одно из (через запятую)' },
  { value: 'gte', label: '≥' }, { value: 'lte', label: '≤' }, { value: 'contains', label: 'содержит' },
  { value: 'empty', label: 'пусто' }, { value: 'not_empty', label: 'не пусто' },
];
const VARS_HINT = '{name} {full_name} {vacancy} {city} {schedule} {salary} {address} {requirements} и ответы: {имя_переменной}';

const tx = (t: Texts | undefined, lang: 'ru' | 'kk') => (typeof t === 'string' ? (lang === 'ru' ? t : '') : t?.[lang] ?? '');

/** Порядок шагов: обход от первого, затем «висящие». */
function orderNodes(g: ScenarioGraph): string[] {
  const seen: string[] = [];
  const visit = (id: string | null | undefined) => {
    if (!id || seen.includes(id) || !g.nodes[id]) return;
    seen.push(id);
    const n = g.nodes[id];
    [n.next, ...(n.options ?? []).map((o) => o.next), ...(n.rules ?? []).map((r) => r.next), n.else, n.on_timeout, n.empty].forEach(visit);
  };
  visit(g.start);
  return [...seen, ...Object.keys(g.nodes).filter((id) => !seen.includes(id))];
}

function targets(n: ScenarioNode): string[] {
  return [n.next, ...(n.options ?? []).map((o) => o.next), ...(n.rules ?? []).map((r) => r.next), n.else, n.on_timeout, n.empty]
    .filter(Boolean) as string[];
}

export default function ScenarioEditor() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const editable = can('admin', 'lead');
  const q = useQuery({ queryKey: ['scenario', id], queryFn: () => api<Scenario>(`/scenarios/${id}`) });
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates') });
  const [meta, setMeta] = useState({ name: '', kind: 'custom', description: '', is_active: true });
  const [graph, setGraph] = useState<ScenarioGraph | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [json, setJson] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (q.data) {
      setMeta({ name: q.data.name, kind: q.data.kind, description: q.data.description ?? '', is_active: q.data.is_active });
      setGraph(q.data.graph);
      setSel(q.data.graph.start);
      setDirty(false);
    }
  }, [q.data]);

  const [debounced] = useDebouncedValue(graph, 400);
  const validation = useQuery({
    queryKey: ['validate', debounced],
    queryFn: () => api<{ ok: boolean; errors: string[] }>('/scenarios/validate', { method: 'POST', json: debounced }),
    enabled: !!debounced,
  });

  const save = useMutation({
    mutationFn: () => api<Scenario>(`/scenarios/${id}`, { method: 'PUT', json: { ...meta, graph } }),
    onSuccess: (s) => { qc.setQueryData(['scenario', id], s); void qc.invalidateQueries({ queryKey: ['scenarios'] }); notifyOk(`Сохранено, версия ${s.version}`); setDirty(false); },
    onError: (e) => {
      if (e instanceof ApiError && typeof e.detail === 'object' && e.detail && 'errors' in e.detail) {
        notifyError(new Error((e.detail as { errors: string[] }).errors.slice(0, 3).join('; ')));
      } else notifyError(e);
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/scenarios/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['scenarios'] }); nav('/scenarios'); },
    onError: notifyError,
  });

  const order = useMemo(() => (graph ? orderNodes(graph) : []), [graph]);
  if (!graph) return <Text>Загрузка…</Text>;

  const update = (g: ScenarioGraph) => { setGraph(g); setDirty(true); };
  const setNode = (nid: string, patch: Partial<ScenarioNode>) => update({ ...graph, nodes: { ...graph.nodes, [nid]: { ...graph.nodes[nid], ...patch } } });
  const addNode = (type: string) => {
    let i = Object.keys(graph.nodes).length + 1;
    while (graph.nodes[`step${i}`]) i++;
    const nid = `step${i}`;
    const base: ScenarioNode = { type, title: NODE_TYPES[type].label };
    if (WITH_TEXT.has(type)) base.text = { ru: '', kk: '' };
    if (type === 'buttons' || type === 'template') base.options = [{ id: 'yes', label: { ru: 'Да', kk: 'Иә' }, next: null }, { id: 'no', label: { ru: 'Нет', kk: 'Жоқ' }, next: null }];
    if (type === 'condition') { base.rules = [{ var: '', op: 'eq', value: '', next: null }]; base.else = null; }
    if (type === 'template') { base.template = ''; base.params = []; }
    update({ ...graph, nodes: { ...graph.nodes, [nid]: base } });
    setSel(nid);
  };
  const deleteNode = (nid: string) => {
    if (nid === graph.start) return notifyError(new Error('Нельзя удалить первый шаг — сначала назначьте первым другой'));
    const nodes = { ...graph.nodes };
    delete nodes[nid];
    update({ ...graph, nodes });
    setSel(graph.start);
  };
  const nodeOptions = order.map((n) => ({ value: n, label: `${graph.nodes[n].title || n} (${n})` }));
  const node = sel ? graph.nodes[sel] : null;
  const approvedNames = Array.from(new Set((templates.data ?? []).filter((t) => t.status === 'APPROVED').map((t) => t.name)));

  return (
    <>
      <Group justify="space-between" mb="md">
        <Group>
          <ActionIcon variant="subtle" onClick={() => nav('/scenarios')} aria-label="Назад"><IconArrowLeft /></ActionIcon>
          <Title order={2}>{meta.name}</Title>
          <Badge variant="light">v{q.data?.version}</Badge>
          {(q.data?.running ?? 0) > 0 && <Badge color="teal">в диалогах: {q.data?.running}</Badge>}
        </Group>
        {editable && (
          <Group>
            <Button color="red" variant="subtle" onClick={() => window.confirm('Удалить сценарий?') && remove.mutate()}>Удалить</Button>
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>Сохранить</Button>
          </Group>
        )}
      </Group>

      <Paper withBorder p="sm" mb="md">
        <Group grow align="flex-end">
          <TextInput label="Название" value={meta.name} disabled={!editable} onChange={(e) => { setMeta({ ...meta, name: e.currentTarget.value }); setDirty(true); }} />
          <Select label="Тип" data={Object.entries(KINDS).map(([value, label]) => ({ value, label }))} value={meta.kind} disabled={!editable}
            onChange={(v) => { if (v) { setMeta({ ...meta, kind: v }); setDirty(true); } }} />
          <Switch label="Включён" checked={meta.is_active} disabled={!editable} onChange={(e) => { setMeta({ ...meta, is_active: e.currentTarget.checked }); setDirty(true); }} />
        </Group>
        {(q.data?.running ?? 0) > 0 && <Text size="xs" c="orange" mt="xs">Диалоги, которые уже идут, продолжат по новой версии со своего текущего шага.</Text>}
      </Paper>

      {validation.data && !validation.data.ok && (
        <Alert color="orange" mb="md" title="Проверка сценария">
          {validation.data.errors.slice(0, 8).map((e) => <Text key={e} size="sm">• {e}</Text>)}
        </Alert>
      )}

      <Tabs defaultValue="steps">
        <Tabs.List mb="sm">
          <Tabs.Tab value="steps">Шаги</Tabs.Tab>
          <Tabs.Tab value="json" onClick={() => setJson(JSON.stringify(graph, null, 2))}>JSON</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="steps">
          <Grid>
            <Grid.Col span={{ base: 12, md: 5 }}>
              <ScrollArea h="calc(100vh - 330px)" type="auto">
                <Stack gap="xs" pr="xs">
                  {order.map((nid, i) => {
                    const n = graph.nodes[nid];
                    const t = NODE_TYPES[n.type] ?? { label: n.type, color: 'gray' };
                    return (
                      <Card key={nid} withBorder padding="xs" onClick={() => setSel(nid)} style={{ cursor: 'pointer',
                        borderColor: sel === nid ? 'var(--mantine-color-teal-6)' : undefined, borderWidth: sel === nid ? 2 : 1 }}>
                        <Group justify="space-between" wrap="nowrap">
                          <Group gap={6} wrap="nowrap">
                            <Text size="xs" c="dimmed" w={20}>{i + 1}</Text>
                            {graph.start === nid && <Tooltip label="Первый шаг"><IconFlag size={14} color="var(--mantine-color-teal-6)" /></Tooltip>}
                            <Text size="sm" fw={500} lineClamp={1}>{n.title || nid}</Text>
                          </Group>
                          <Badge size="xs" color={t.color} variant="light">{t.label}</Badge>
                        </Group>
                        {WITH_TEXT.has(n.type) && <Text size="xs" c="dimmed" lineClamp={2} mt={4}>{tx(n.text, 'ru')}</Text>}
                        {n.type === 'template' && <Text size="xs" c="dimmed" mt={4}>шаблон: {n.template || '—'}</Text>}
                        {targets(n).length > 0 && <Text size="xs" c="dimmed" mt={2}>→ {Array.from(new Set(targets(n))).map((x) => graph.nodes[x]?.title || x).join(', ')}</Text>}
                      </Card>
                    );
                  })}
                  {editable && (
                    <Menu position="bottom-start">
                      <Menu.Target><Button variant="light" leftSection={<IconPlus size={16} />}>Добавить шаг</Button></Menu.Target>
                      <Menu.Dropdown>
                        {Object.entries(NODE_TYPES).map(([k, v]) => <Menu.Item key={k} onClick={() => addNode(k)}>{v.label}</Menu.Item>)}
                      </Menu.Dropdown>
                    </Menu>
                  )}
                </Stack>
              </ScrollArea>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 7 }}>
              {node && sel && (
                <NodeForm key={sel} nid={sel} node={node} isStart={graph.start === sel} editable={editable} nodeOptions={nodeOptions.filter((o) => o.value !== sel)}
                  templateNames={approvedNames} onChange={(p) => setNode(sel, p)} onDelete={() => deleteNode(sel)}
                  onMakeStart={() => update({ ...graph, start: sel })} />
              )}
            </Grid.Col>
          </Grid>
        </Tabs.Panel>
        <Tabs.Panel value="json">
          <JsonInput autosize minRows={20} maxRows={40} value={json} onChange={setJson} validationError="Неверный JSON" formatOnBlur readOnly={!editable} />
          {editable && <Button mt="sm" variant="light" onClick={() => { try { update(JSON.parse(json)); notifyOk('Применено'); } catch { notifyError(new Error('Неверный JSON')); } }}>Применить JSON</Button>}
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

function TextsInput({ label, value, onChange, disabled }: { label: string; value: Texts | undefined; onChange: (t: Texts) => void; disabled: boolean }) {
  const obj = typeof value === 'string' ? { ru: value } : value ?? {};
  return (
    <Grid>
      <Grid.Col span={{ base: 12, sm: 6 }}>
        <Textarea label={`${label} — русский`} autosize minRows={2} value={obj.ru ?? ''} disabled={disabled} onChange={(e) => onChange({ ...obj, ru: e.currentTarget.value })} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, sm: 6 }}>
        <Textarea label={`${label} — қазақша`} autosize minRows={2} value={obj.kk ?? ''} disabled={disabled} onChange={(e) => onChange({ ...obj, kk: e.currentTarget.value })} />
      </Grid.Col>
    </Grid>
  );
}

function NodeForm({ nid, node, isStart, editable, nodeOptions, templateNames, onChange, onDelete, onMakeStart }: {
  nid: string; node: ScenarioNode; isStart: boolean; editable: boolean; nodeOptions: { value: string; label: string }[];
  templateNames: string[]; onChange: (p: Partial<ScenarioNode>) => void; onDelete: () => void; onMakeStart: () => void;
}) {
  const t = NODE_TYPES[node.type];
  const d = !editable;
  const nextSel = (label: string, value: string | null | undefined, set: (v: string | null) => void, clearable = true) => (
    <Select label={label} data={nodeOptions} value={value ?? null} onChange={set} clearable={clearable} searchable disabled={d} placeholder="— завершить сценарий —" />
  );
  const setOption = (i: number, p: Partial<ScenarioOption>) => onChange({ options: (node.options ?? []).map((o, j) => (j === i ? { ...o, ...p } : o)) });
  const setRule = (i: number, p: Partial<ScenarioRule>) => onChange({ rules: (node.rules ?? []).map((r, j) => (j === i ? { ...r, ...p } : r)) });

  return (
    <Paper withBorder p="md">
      <Stack>
        <Group justify="space-between">
          <Group gap="xs"><Badge color={t?.color}>{t?.label ?? node.type}</Badge><Text size="xs" c="dimmed">id: {nid}</Text></Group>
          {editable && (
            <Group gap="xs">
              {!isStart && <Button size="xs" variant="subtle" leftSection={<IconFlag size={14} />} onClick={onMakeStart}>Сделать первым</Button>}
              <ActionIcon color="red" variant="subtle" onClick={onDelete} aria-label="Удалить шаг"><IconTrash size={16} /></ActionIcon>
            </Group>
          )}
        </Group>
        {t && <Text size="xs" c="dimmed">{t.hint}</Text>}
        <TextInput label="Подпись шага (для вас)" value={node.title ?? ''} disabled={d} onChange={(e) => onChange({ title: e.currentTarget.value })} />

        {node.type === 'template' && (
          <>
            <Select label="Шаблон" data={templateNames} value={node.template || null} disabled={d} searchable
              description="Язык подставится по кандидату (ru/kk)" onChange={(v) => onChange({ template: v ?? '' })} />
            <TextInput label="Параметры {{1}}, {{2}}… (через «|»)" value={(node.params ?? []).join(' | ')} disabled={d}
              description={VARS_HINT} onChange={(e) => onChange({ params: e.currentTarget.value.split('|').map((x) => x.trim()) })} />
          </>
        )}
        {WITH_TEXT.has(node.type) && (
          <>
            <TextsInput label="Текст" value={node.text} disabled={d} onChange={(text) => onChange({ text })} />
            <Text size="xs" c="dimmed">Подстановки: {VARS_HINT}</Text>
          </>
        )}

        {(node.type === 'buttons' || node.type === 'template') && (
          <Stack gap={6}>
            <Text size="sm" fw={500}>Варианты ответа {node.type === 'template' && '(подписи должны совпадать с кнопками шаблона)'}</Text>
            {(node.options ?? []).map((o, i) => (
              <Group key={i} gap={6} wrap="nowrap" align="flex-end">
                <TextInput w={80} label={i === 0 ? 'id' : undefined} value={o.id} disabled={d} onChange={(e) => setOption(i, { id: e.currentTarget.value })} />
                <TextInput style={{ flex: 1 }} label={i === 0 ? 'Русский' : undefined} value={o.label.ru ?? ''} maxLength={24} disabled={d}
                  onChange={(e) => setOption(i, { label: { ...o.label, ru: e.currentTarget.value } })} />
                <TextInput style={{ flex: 1 }} label={i === 0 ? 'Қазақша' : undefined} value={o.label.kk ?? ''} maxLength={24} disabled={d}
                  onChange={(e) => setOption(i, { label: { ...o.label, kk: e.currentTarget.value } })} />
                <Select style={{ flex: 1.3 }} label={i === 0 ? 'Дальше' : undefined} data={nodeOptions} value={o.next} searchable disabled={d}
                  onChange={(v) => setOption(i, { next: v })} />
                {editable && <ActionIcon color="red" variant="subtle" mb={4} onClick={() => onChange({ options: (node.options ?? []).filter((_, j) => j !== i) })} aria-label="Удалить"><IconTrash size={14} /></ActionIcon>}
              </Group>
            ))}
            {editable && (node.options ?? []).length < 10 && (
              <Button size="xs" variant="subtle" w="fit-content" onClick={() => onChange({ options: [...(node.options ?? []), { id: `opt${(node.options ?? []).length + 1}`, label: { ru: '', kk: '' }, next: null }] })}>+ вариант</Button>
            )}
            <Text size="xs" c="dimmed">Кнопка — до 20 символов. Больше 3 вариантов — отправится списком.</Text>
          </Stack>
        )}

        {(node.type === 'buttons' || node.type === 'template' || node.type === 'question') && (
          <TextInput label="Сохранить ответ в переменную" placeholder="например experience" value={node.var ?? ''} disabled={d}
            onChange={(e) => onChange({ var: e.currentTarget.value.replace(/[^a-z0-9_]/gi, '').toLowerCase() || undefined })} />
        )}
        {node.type === 'question' && (
          <Select label="Тип ответа" data={[{ value: 'text', label: 'Текст' }, { value: 'number', label: 'Число' }]} value={node.expect ?? 'text'} disabled={d}
            onChange={(v) => onChange({ expect: (v as 'text' | 'number') ?? 'text' })} />
        )}

        {node.type === 'condition' && (
          <Stack gap={6}>
            <Text size="sm" fw={500}>Правила (проверяются сверху вниз)</Text>
            {(node.rules ?? []).map((r, i) => (
              <Group key={i} gap={6} wrap="nowrap" align="flex-end">
                <TextInput style={{ flex: 1 }} label={i === 0 ? 'Переменная' : undefined} value={r.var} disabled={d} onChange={(e) => setRule(i, { var: e.currentTarget.value })} />
                <Select w={150} label={i === 0 ? 'Операция' : undefined} data={OPS} value={r.op} disabled={d} onChange={(v) => setRule(i, { op: v ?? 'eq' })} />
                <TextInput style={{ flex: 1 }} label={i === 0 ? 'Значение (id варианта)' : undefined} disabled={d}
                  value={Array.isArray(r.value) ? r.value.join(', ') : String(r.value ?? '')}
                  onChange={(e) => setRule(i, { value: r.op === 'in' ? e.currentTarget.value.split(',').map((x) => x.trim()) : e.currentTarget.value })} />
                <Select style={{ flex: 1.3 }} label={i === 0 ? 'Тогда' : undefined} data={nodeOptions} value={r.next} searchable disabled={d} onChange={(v) => setRule(i, { next: v })} />
                {editable && <ActionIcon color="red" variant="subtle" mb={4} onClick={() => onChange({ rules: (node.rules ?? []).filter((_, j) => j !== i) })} aria-label="Удалить"><IconTrash size={14} /></ActionIcon>}
              </Group>
            ))}
            {editable && <Button size="xs" variant="subtle" w="fit-content" onClick={() => onChange({ rules: [...(node.rules ?? []), { var: '', op: 'eq', value: '', next: null }] })}>+ правило</Button>}
            {nextSel('Иначе', node.else, (v) => onChange({ else: v }), false)}
          </Stack>
        )}

        {node.type === 'set' && (
          <Group grow>
            <Select label="Результат скрининга" data={screeningOptions} value={node.screening ?? null} clearable disabled={d} onChange={(v) => onChange({ screening: (v as ScenarioNode['screening']) ?? null })} />
            <Select label="Статус по вакансии" data={statusOptions} value={node.status ?? null} clearable disabled={d} onChange={(v) => onChange({ status: v })} />
            <Select label="Кадровый резерв" data={[{ value: 'keep', label: 'не менять' }, { value: 'yes', label: 'добавить' }, { value: 'no', label: 'убрать' }]}
              value={node.reserve === undefined ? 'keep' : node.reserve ? 'yes' : 'no'} disabled={d}
              onChange={(v) => onChange(v === 'keep' ? { reserve: undefined } : { reserve: v === 'yes' })} />
          </Group>
        )}
        {node.type === 'handoff' && (
          <TextInput label="Причина (видна рекрутеру)" value={node.reason ?? ''} disabled={d} onChange={(e) => onChange({ reason: e.currentTarget.value })} />
        )}

        {WITH_NEXT.has(node.type) && nextSel('Следующий шаг', node.next, (v) => onChange({ next: v }), node.type === 'message')}
        {node.type === 'vacancy_choice' && nextSel('Если вакансий нет', node.empty, (v) => onChange({ empty: v }))}

        {WAITING.has(node.type) && node.type !== 'language' && (
          <Group grow align="flex-end">
            <NumberInput label="Ждать ответа, часов" description="Пусто — ждать бесконечно" min={1} max={720} value={node.timeout_hours ?? ''} disabled={d}
              onChange={(v) => onChange({ timeout_hours: v === '' ? null : Number(v) })} />
            {node.timeout_hours ? nextSel('Если не ответил', node.on_timeout, (v) => onChange({ on_timeout: v })) : <span />}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
