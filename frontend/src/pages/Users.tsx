import { Badge, Button, Group, Modal, Paper, PasswordInput, Select, Stack, Switch, Table, TextInput, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type Role, type User } from '../api';
import { notifyError, notifyOk, useUsers } from '../hooks';
import { dt, roleOptions, ROLES } from '../labels';

export default function UsersPage() {
  const users = useUsers();
  const [edit, setEdit] = useState<User | 'new' | null>(null);
  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={2}>Пользователи</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit('new')}>Добавить</Button>
      </Group>
      <Paper withBorder style={{ overflowX: 'auto' }}>
        <Table highlightOnHover miw={600}>
          <Table.Thead><Table.Tr><Table.Th>Имя</Table.Th><Table.Th>Логин</Table.Th><Table.Th>Роль</Table.Th><Table.Th>Последний вход</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {(users.data ?? []).map((u) => (
              <Table.Tr key={u.id} style={{ cursor: 'pointer' }} onClick={() => setEdit(u)}>
                <Table.Td>{u.full_name}</Table.Td><Table.Td>{u.login}</Table.Td><Table.Td>{ROLES[u.role]}</Table.Td>
                <Table.Td>{dt(u.last_login_at)}</Table.Td>
                <Table.Td>{!u.is_active && <Badge color="gray">отключён</Badge>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      {edit && <UserModal user={edit === 'new' ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function UserModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ login: user?.login ?? '', full_name: user?.full_name ?? '', role: (user?.role ?? 'recruiter') as Role,
    is_active: user?.is_active ?? true, password: '' });
  const save = useMutation({
    mutationFn: () => user
      ? api(`/users/${user.id}`, { method: 'PATCH', json: { full_name: f.full_name, role: f.role, is_active: f.is_active, ...(f.password ? { password: f.password } : {}) } })
      : api('/users', { method: 'POST', json: { login: f.login, full_name: f.full_name, role: f.role, password: f.password } }),
    onSuccess: () => { notifyOk('Сохранено'); void qc.invalidateQueries({ queryKey: ['users'] }); onClose(); },
    onError: notifyError,
  });
  return (
    <Modal opened onClose={onClose} title={user ? 'Пользователь' : 'Новый пользователь'}>
      <Stack>
        <TextInput label="Логин" disabled={!!user} value={f.login} onChange={(e) => setF({ ...f, login: e.currentTarget.value })} />
        <TextInput label="Имя" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.currentTarget.value })} />
        <Select label="Роль" data={roleOptions} value={f.role} onChange={(v) => v && setF({ ...f, role: v as Role })} />
        <PasswordInput label={user ? 'Новый пароль (если нужно сменить)' : 'Пароль'} description="Минимум 8 символов"
          value={f.password} onChange={(e) => setF({ ...f, password: e.currentTarget.value })} />
        {user && <Switch label="Активен" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.currentTarget.checked })} />}
        <Group justify="flex-end"><Button loading={save.isPending} onClick={() => save.mutate()}>Сохранить</Button></Group>
      </Stack>
    </Modal>
  );
}
