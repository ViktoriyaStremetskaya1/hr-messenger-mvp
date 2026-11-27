import { AppShell, Badge, Burger, Group, NavLink, Stack, Text, Title, Tooltip } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconBrandWhatsapp,
  IconBriefcase,
  IconCalendar,
  IconChartFunnel,
  IconHistory,
  IconLogout,
  IconMessages,
  IconRoute,
  IconSend,
  IconSettings,
  IconUsers,
  IconUsersGroup,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { NavLink as RouterLink, Outlet, useLocation } from 'react-router-dom';

import { api, type ChannelStatus } from '../api';
import { useAuth } from '../auth';
import { ROLES } from '../labels';

interface Item {
  to: string;
  label: string;
  icon: ReactNode;
  soon?: string;
  show?: boolean;
}

export default function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { user, logout, can } = useAuth();
  const { pathname } = useLocation();
  const ch = useQuery({ queryKey: ['channel'], queryFn: () => api<ChannelStatus>('/channel/status'), staleTime: 60_000 });

  const items: Item[] = [
    { to: '/candidates', label: 'Кандидаты', icon: <IconUsersGroup size={18} /> },
    { to: '/vacancies', label: 'Вакансии', icon: <IconBriefcase size={18} /> },
    { to: '/inbox', label: 'Чаты', icon: <IconMessages size={18} />, soon: 'Этап 6' },
    { to: '/templates', label: 'Шаблоны WhatsApp', icon: <IconBrandWhatsapp size={18} /> },
    { to: '/scenarios', label: 'Сценарии', icon: <IconRoute size={18} /> },
    { to: '/campaigns', label: 'Рассылки', icon: <IconSend size={18} /> },
    { to: '/slots', label: 'Собеседования', icon: <IconCalendar size={18} />, soon: 'Этап 5' },
    { to: '/analytics', label: 'Аналитика', icon: <IconChartFunnel size={18} />, soon: 'Этап 7' },
    { to: '/users', label: 'Пользователи', icon: <IconUsers size={18} />, show: can('admin') },
    { to: '/audit', label: 'Журнал действий', icon: <IconHistory size={18} />, show: can('admin', 'lead') },
    { to: '/settings', label: 'Настройки', icon: <IconSettings size={18} /> },
  ];

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Меню" />
            <Title order={4}>HR Messenger</Title>
            {ch.data && (
              <Tooltip label={ch.data.mode === 'mock' ? 'Сообщения уходят в мок WhatsApp, реальным людям ничего не отправляется' : 'WhatsApp Cloud API'}>
                <Badge color={ch.data.mode === 'mock' ? 'blue' : 'green'} variant="light">{ch.data.mode === 'mock' ? 'Песочница' : 'WhatsApp: боевой'}</Badge>
              </Tooltip>
            )}
          </Group>
          <Group gap="xs" visibleFrom="xs">
            <Text size="sm">{user?.full_name}</Text>
            <Badge variant="light">{user ? ROLES[user.role] : ''}</Badge>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <Stack gap={2} style={{ flex: 1 }}>
          {items
            .filter((i) => i.show !== false)
            .map((i) =>
              i.soon ? (
                <Tooltip key={i.to} label={`Появится: ${i.soon}`} position="right">
                  <NavLink label={i.label} leftSection={i.icon} disabled />
                </Tooltip>
              ) : (
                <NavLink
                  key={i.to}
                  component={RouterLink}
                  to={i.to}
                  label={i.label}
                  leftSection={i.icon}
                  active={pathname.startsWith(i.to)}
                  onClick={close}
                />
              ),
            )}
        </Stack>
        <NavLink label="Выйти" leftSection={<IconLogout size={18} />} onClick={() => void logout()} />
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
