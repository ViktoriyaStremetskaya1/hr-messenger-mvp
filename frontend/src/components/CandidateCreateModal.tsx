import { Button, Group, Modal, Select, Stack, Switch, TextInput } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, type Candidate } from '../api';
import { notifyError, useVacancies, vacancyLabel } from '../hooks';

const EMPTY = { full_name: '', phone: '', city: '', source: '', vacancy_id: null as string | null, is_reserve: false };

export default function CandidateCreateModal({ opened, onClose, onCreated }: {
  opened: boolean; onClose: () => void; onCreated: (id: number) => void;
}) {
  const qc = useQueryClient();
  const vacancies = useVacancies();
  const [f, setF] = useState(EMPTY);
  const create = useMutation({
    mutationFn: () => api<Candidate>('/candidates', { method: 'POST', json: {
      ...f, city: f.city || null, source: f.source || null, vacancy_id: f.vacancy_id ? Number(f.vacancy_id) : null } }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['candidates'] });
      setF(EMPTY);
      onClose();
      onCreated(c.id);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        const dupId = (e.detail as { candidate_id?: number })?.candidate_id;
        onClose();
        if (dupId) onCreated(dupId);
      }
      notifyError(e);
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Новый кандидат">
      <Stack>
        <TextInput label="ФИО" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.currentTarget.value })} />
        <TextInput label="Телефон" required placeholder="+7 777 123 45 67" value={f.phone} onChange={(e) => setF({ ...f, phone: e.currentTarget.value })} />
        <Group grow>
          <TextInput label="Город" value={f.city} onChange={(e) => setF({ ...f, city: e.currentTarget.value })} />
          <TextInput label="Источник" value={f.source} onChange={(e) => setF({ ...f, source: e.currentTarget.value })} />
        </Group>
        <Select label="Вакансия" clearable searchable value={f.vacancy_id} onChange={(v) => setF({ ...f, vacancy_id: v })}
          data={(vacancies.data ?? []).filter((v) => v.is_active).map((v) => ({ value: String(v.id), label: vacancyLabel(v) }))} />
        <Switch label="Кадровый резерв" checked={f.is_reserve} onChange={(e) => setF({ ...f, is_reserve: e.currentTarget.checked })} />
        <Group justify="flex-end">
          <Button disabled={!f.full_name || !f.phone} loading={create.isPending} onClick={() => create.mutate()}>Создать</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
