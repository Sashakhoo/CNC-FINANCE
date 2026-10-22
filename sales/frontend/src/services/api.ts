import { QueryClient } from '@tanstack/react-query';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch('/api' + path, {
    method: init.method ?? (init.body === undefined ? 'GET' : 'POST'),
    credentials: 'same-origin',
    headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON error */ }
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ') : 'Request failed';
    throw new ApiError(res.status, message || 'Request failed');
  }
  return res.json() as Promise<T>;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, err) => !(err instanceof ApiError && [401, 403, 404, 422].includes(err.status)) && count < 2,
    },
  },
});

export interface Me { id: number; username: string; role: 'ADMIN' | 'SALES' | 'VIEWER'; finance_role: string; can_edit: boolean; finance_url: string }

/** Multipart upload (file + fields). */
export async function apiForm<T = unknown>(path: string, form: FormData): Promise<T> {
  const res = await fetch('/api' + path, { method: 'POST', credentials: 'same-origin', body: form });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON error */ }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : 'Upload failed');
  }
  return res.json() as Promise<T>;
}
