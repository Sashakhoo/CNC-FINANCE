import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, type Me } from '../services/api';

export function useMe() {
  return useQuery<Me | null, ApiError>({
    queryKey: ['me'],
    queryFn: async () => {
      try { return await api<Me>('/auth/me'); } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useSetupStatus(enabled: boolean) {
  return useQuery({ queryKey: ['setup'], queryFn: () => api<{ needs_setup: boolean; finance_url: string }>('/auth/setup'), enabled });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) => api('/auth/login', { body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSettled: () => { qc.clear(); qc.setQueryData(['me'], null); },
  });
}
