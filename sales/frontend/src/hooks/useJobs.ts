import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { qs } from './useCrm';
import type { SearchCriteria } from '../components/discovery/DiscoveryForm';
import type { Paged } from '../types';

export type JobStatus = 'QUEUED' | 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
export interface JobMessage { at: string; message: string; [k: string]: string }
export interface Job {
  id: number; name: string; job_type: string; status: JobStatus; search_id: number | null; provider: string | null;
  params: Record<string, unknown>; counters: Record<string, number>; progress: number; stage: string | null;
  records_processed: number; records_created: number; warnings?: JobMessage[]; errors?: JobMessage[];
  warning_count: number; error_count: number; cancel_requested: boolean; started_at: string | null; finished_at: string | null;
  created_at: string; duration_seconds: number | null; user: string | null;
  crawls?: { company_id: number; company: string; domain: string; status: string; pages_fetched: number; pages_skipped: number; robots_allowed: boolean | null; error: string | null }[];
  provider_calls?: { provider: string; calls: number; errors: number }[];
}
export interface Search { id: number; name: string; criteria: SearchCriteria; created_at: string; last_job: Job | null }

export const ACTIVE: JobStatus[] = ['QUEUED', 'RUNNING', 'PAUSED'];

export function useJob(id: number | null) {
  return useQuery({
    queryKey: ['job', id], enabled: !!id, queryFn: () => api<Job>(`/jobs/${id}`),
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 2000 : false),
  });
}

export function useJobs(params: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ['jobs', params], queryFn: () => api<Paged<Job>>(`/jobs${qs(params)}`), placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((j) => ACTIVE.includes(j.status)) ? 3000 : false),
  });
}

export function useSearches() {
  return useQuery({
    queryKey: ['searches'], queryFn: () => api<Search[]>('/searches'),
    refetchInterval: (q) => (q.state.data?.some((s) => s.last_job && ACTIVE.includes(s.last_job.status)) ? 4000 : false),
  });
}

export interface ProviderRow { kind: string; name: string; selected: boolean; display_name: string; state: string; info: Record<string, unknown> | null }
export interface UsageRow { provider: string; kind: string; requests_today: number; requests_month: number; success_rate: number | null; errors_month: number; avg_ms: number | null; estimated_cost: number | null; last_used: string | null; recent_errors: { at: string; operation: string; error_type: string | null; http_status: number | null }[] }

export const useProviders = () => useQuery({ queryKey: ['providers'], queryFn: () => api<{ providers: ProviderRow[]; usage: UsageRow[] }>('/providers') });
