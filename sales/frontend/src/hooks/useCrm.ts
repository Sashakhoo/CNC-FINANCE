import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { useUi } from '../store/useUi';
import type { CompanyDetail, CompanySummary, ContactDetail, Meta, Paged, Prospect } from '../types';

export function qs(params: Record<string, string | number | boolean | string[] | undefined | null>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    if (Array.isArray(v)) v.forEach((x) => x && p.append(k, x));
    else p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const useMeta = () => useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/meta'), staleTime: 5 * 60_000 });

export function useCompanies(params: Record<string, string | number | boolean | undefined>) {
  return useQuery({ queryKey: ['companies', params], queryFn: () => api<Paged<CompanySummary>>(`/companies${qs(params)}`), placeholderData: keepPreviousData });
}

export const useCompany = (id: number) => useQuery({ queryKey: ['company', id], queryFn: () => api<CompanyDetail>(`/companies/${id}`) });

export function useProspects(params: Record<string, string | number | boolean | string[] | undefined>) {
  return useQuery({ queryKey: ['prospects', params], queryFn: () => api<Paged<Prospect>>(`/prospects${qs(params)}`), placeholderData: keepPreviousData });
}

export const useContact = (id: number) => useQuery({ queryKey: ['contact', id], queryFn: () => api<ContactDetail>(`/contacts/${id}`) });

/** Mutation that refreshes CRM lists afterwards and toasts API errors. */
export function useCrmMutation<TBody, TResult = unknown>(fn: (body: TBody) => Promise<TResult>, opts: { success?: string | ((r: TResult) => string | null); onSuccess?: (r: TResult) => void } = {}) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.toast);
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      ['companies', 'prospects', 'analytics', 'company', 'contact', 'audit', 'suppression', 'searches', 'jobs', 'job', 'providers', 'signals', 'opportunities', 'drafts', 'campaigns'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      const msg = typeof opts.success === 'function' ? opts.success(r) : opts.success;
      if (msg) toast(msg);
      opts.onSuccess?.(r);
    },
    onError: (e: Error) => toast(e.message, 'error'),
  });
}

/** Writes a contact detail response straight into the cache (status/email changes return the full contact). */
export function useSetContact() {
  const qc = useQueryClient();
  return (c: ContactDetail) => qc.setQueryData(['contact', c.id], c);
}
