import { Alert, Button, Group, List, Modal, MultiSelect, Paper, Select, SimpleGrid, Stack, Stepper, Switch, Table, Text, TextInput } from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { IconFileSpreadsheet } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api } from '../api';
import { notifyError, useTags, useVacancies, vacancyLabel } from '../hooks';

interface Preview {
  file_name: string;
  headers: string[];
  mapping: Record<string, string | null>;
  sample: string[][];
  total_rows: number;
}
interface Result {
  total: number;
  created: number;
  updated: number;
  duplicates_in_file: number;
  errors: { line: number; error: string }[];
  unmatched_vacancies: string[];
}

const FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: 'full_name', label: 'ФИО', required: true },
  { key: 'phone', label: 'Телефон', required: true },
  { key: 'city', label: 'Город' },
  { key: 'vacancy', label: 'Вакансия' },
  { key: 'source', label: 'Источник' },
];

export default function ImportWizard({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const vacancies = useVacancies();
  const tags = useTags();
  const [step, setStep] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [opts, setOpts] = useState({ default_vacancy_id: null as string | null, default_source: '', mark_reserve: false, tag_ids: [] as string[] });
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setStep(0); setFile(null); setPreview(null); setResult(null); setMapping({});
    setOpts({ default_vacancy_id: null, default_source: '', mark_reserve: false, tag_ids: [] });
  };
  const close = () => { reset(); onClose(); };

  const upload = async (f: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const p = await api<Preview>('/candidates/import/preview', { method: 'POST', body: fd });
      setFile(f); setPreview(p); setMapping(p.mapping); setStep(1);
    } catch (e) { notifyError(e); } finally { setBusy(false); }
  };

  const commit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('options', JSON.stringify({
        mapping, default_source: opts.default_source || null, mark_reserve: opts.mark_reserve,
        default_vacancy_id: opts.default_vacancy_id ? Number(opts.default_vacancy_id) : null, tag_ids: opts.tag_ids.map(Number),
      }));
      setResult(await api<Result>('/candidates/import', { method: 'POST', body: fd }));
      setStep(2);
      void qc.invalidateQueries({ queryKey: ['candidates'] });
      void qc.invalidateQueries({ queryKey: ['vacancies'] });
    } catch (e) { notifyError(e); } finally { setBusy(false); }
  };

  const headerOptions = (preview?.headers ?? []).map((h) => ({ value: h, label: h }));
  const mappedIdx = FIELDS.map((f) => (mapping[f.key] ? preview?.headers.indexOf(mapping[f.key]!) ?? -1 : -1));

  return (
    <Modal opened={opened} onClose={close} title="Импорт кандидатов" size="xl">
      <Stepper active={step} size="sm" mb="md">
        <Stepper.Step label="Файл" />
        <Stepper.Step label="Колонки" />
        <Stepper.Step label="Результат" />
      </Stepper>

      {step === 0 && (
        <Stack>
          <Dropzone onDrop={(files) => files[0] && void upload(files[0])} loading={busy} maxFiles={1} maxSize={10 * 1024 * 1024}
            accept={['text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel', '.csv', '.xlsx']}>
            <Group justify="center" mih={140} style={{ pointerEvents: 'none' }}>
              <IconFileSpreadsheet size={48} stroke={1.5} />
              <div>
                <Text size="lg">Перетащите файл или нажмите, чтобы выбрать</Text>
                <Text size="sm" c="dimmed">.xlsx или .csv до 10 МБ. Первая строка — заголовки. Колонки: ФИО, Телефон, Город, Вакансия, Источник</Text>
              </div>
            </Group>
          </Dropzone>
          <Text size="xs" c="dimmed">Файл не сохраняется на сервере. Дубли по телефону объединяются, существующие кандидаты дозаполняются.</Text>
        </Stack>
      )}

      {step === 1 && preview && (
        <Stack>
          <Text size="sm">Файл <b>{preview.file_name}</b>, строк: {preview.total_rows}</Text>
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            {FIELDS.map((f) => (
              <Select key={f.key} label={f.label} required={f.required} data={headerOptions} clearable={!f.required}
                value={mapping[f.key] ?? null} onChange={(v) => setMapping({ ...mapping, [f.key]: v })} />
            ))}
          </SimpleGrid>
          <Paper withBorder style={{ overflowX: 'auto' }}>
            <Table fz="xs">
              <Table.Thead><Table.Tr>{FIELDS.map((f) => <Table.Th key={f.key}>{f.label}</Table.Th>)}</Table.Tr></Table.Thead>
              <Table.Tbody>
                {preview.sample.slice(0, 5).map((r, i) => (
                  <Table.Tr key={i}>{mappedIdx.map((idx, j) => <Table.Td key={j}>{idx >= 0 ? r[idx] : '—'}</Table.Td>)}</Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Вакансия по умолчанию" description="Для строк без вакансии" clearable searchable value={opts.default_vacancy_id}
              onChange={(v) => setOpts({ ...opts, default_vacancy_id: v })}
              data={(vacancies.data ?? []).filter((v) => v.is_active).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
            <TextInput label="Источник по умолчанию" description="Для строк без источника" value={opts.default_source}
              onChange={(e) => setOpts({ ...opts, default_source: e.currentTarget.value })} />
            <MultiSelect label="Добавить теги" data={(tags.data ?? []).map((t) => ({ value: String(t.id), label: t.name }))}
              value={opts.tag_ids} onChange={(v) => setOpts({ ...opts, tag_ids: v })} />
            <Switch mt="xl" label="Добавить всех в кадровый резерв" checked={opts.mark_reserve}
              onChange={(e) => setOpts({ ...opts, mark_reserve: e.currentTarget.checked })} />
          </SimpleGrid>
          <Group justify="space-between">
            <Button variant="default" onClick={reset}>Другой файл</Button>
            <Button onClick={commit} loading={busy} disabled={!mapping.full_name || !mapping.phone}>Импортировать</Button>
          </Group>
        </Stack>
      )}

      {step === 2 && result && (
        <Stack>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <Stat label="Строк в файле" value={result.total} />
            <Stat label="Добавлено" value={result.created} />
            <Stat label="Обновлено" value={result.updated} />
            <Stat label="Дублей в файле" value={result.duplicates_in_file} />
          </SimpleGrid>
          {result.unmatched_vacancies.length > 0 && (
            <Alert color="yellow" title="Вакансии не найдены">
              {result.unmatched_vacancies.join(', ')} — сохранены как «желаемая должность». Создайте вакансии и привяжите кандидатов.
            </Alert>
          )}
          {result.errors.length > 0 && (
            <Alert color="red" title={`Пропущено строк: ${result.errors.length}`}>
              <List size="sm" spacing={2}>
                {result.errors.slice(0, 30).map((e) => <List.Item key={e.line}>Строка {e.line}: {e.error}</List.Item>)}
              </List>
              {result.errors.length > 30 && <Text size="sm">…и ещё {result.errors.length - 30}</Text>}
            </Alert>
          )}
          <Group justify="flex-end"><Button onClick={close}>Готово</Button></Group>
        </Stack>
      )}
    </Modal>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Paper withBorder p="sm">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="xl" fw={600}>{value}</Text>
    </Paper>
  );
}
