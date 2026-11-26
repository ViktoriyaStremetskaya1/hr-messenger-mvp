import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, type ReactNode } from 'react';

import { api, ApiError, type Role, type User } from './api';

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (...roles: Role[]) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api<User>('/auth/me');
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: Infinity,
  });
  const user = me.data ?? null;
  const value: AuthCtx = {
    user,
    loading: me.isLoading,
    login: async (login, password) => {
      const u = await api<User>('/auth/login', { method: 'POST', json: { login, password } });
      qc.setQueryData(['me'], u);
    },
    logout: async () => {
      await api('/auth/logout', { method: 'POST' });
      qc.clear();
      qc.setQueryData(['me'], null);
    },
    can: (...roles) => !!user && roles.includes(user.role),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('AuthProvider missing');
  return c;
}
