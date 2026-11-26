import { Alert, Button, Center, Paper, PasswordInput, Stack, TextInput, Title } from '@mantine/core';
import { useState, type FormEvent } from 'react';

import { useAuth } from '../auth';

export default function LoginPage() {
  const { login } = useAuth();
  const [form, setForm] = useState({ login: '', password: '' });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(form.login, form.password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка входа');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w="100%" maw={380}>
        <form onSubmit={submit}>
          <Stack>
            <Title order={3}>Вход в HR Messenger</Title>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label="Логин" autoComplete="username" required value={form.login}
              onChange={(e) => setForm({ ...form, login: e.currentTarget.value })} />
            <PasswordInput label="Пароль" autoComplete="current-password" required value={form.password}
              onChange={(e) => setForm({ ...form, password: e.currentTarget.value })} />
            <Button type="submit" loading={busy}>Войти</Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
