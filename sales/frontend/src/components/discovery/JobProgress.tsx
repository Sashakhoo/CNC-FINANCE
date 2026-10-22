import clsx from 'clsx';
import { AlertTriangle, Ban, CheckCircle2, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { api } from '../../services/api';
import { useCrmMutation } from '../../hooks/useCrm';
import { ACTIVE, type Job } from '../../hooks/useJobs';
import { Bar } from '../common/Misc';
import { fmtDateTime } from '../../utils/format';

export const COUNTER_LABELS: [string, string][] = [
  ['companies_discovered', 'Companies discovered'], ['domains_resolved', 'Domains resolved'], ['websites_crawled', 'Websites crawled'],
  ['contacts_discovered', 'Contacts discovered'], ['profiles_found', 'Professional profiles'], ['emails_discovered', 'Emails discovered'],
  ['emails_verified', 'Emails verified'], ['training_opportunities', 'Training opportunities'], ['high_priority', 'High priority leads'],
];

export function StatusPill({ status }: { status: Job['status'] }) {
  const icon = status === 'RUNNING' ? <Loader2 size={12} className="animate-spin" /> : status === 'COMPLETED' ? <CheckCircle2 size={12} />
    : status === 'FAILED' ? <XCircle size={12} /> : status === 'CANCELLED' ? <Ban size={12} /> : null;
  return (
    <span className={clsx('inline-flex items-center gap-1.5 h-6 px-2.5 rounded-full border text-[10.5px] font-semibold tracking-[0.06em]',
      status === 'RUNNING' ? 'bg-lime text-ink border-lime' : status === 'COMPLETED' ? 'text-fg border-line2'
        : status === 'FAILED' ? 'text-danger border-danger/30 bg-danger-soft' : 'text-mute border-line')}>{icon}{status}</span>
  );
}

export const fmtDuration = (s: number | null) => s === null ? '—' : s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;

export function JobProgress({ job, canEdit, onRetried }: { job: Job; canEdit?: boolean; onRetried?: (j: Job) => void }) {
  const cancel = useCrmMutation(() => api(`/jobs/${job.id}/cancel`, { body: {} }), { success: 'Cancelling…' });
  const retry = useCrmMutation(() => api<Job>(`/jobs/${job.id}/retry`, { body: {} }), { success: 'Retry queued', onSuccess: onRetried });
  const active = ACTIVE.includes(job.status);
  return (
    <section className="card card-pad" aria-label={`Job ${job.name}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow">{job.job_type} job #{job.id}</div>
          <h2 className="h-display text-2xl mt-1 uppercase tracking-tight">{job.name}</h2>
          <p className="text-xs text-mute mt-1">{job.stage ?? 'Waiting for a worker…'} · {fmtDuration(job.duration_seconds)}{job.provider ? ` · ${job.provider}` : ''}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill status={job.status} />
          {canEdit && active && !job.cancel_requested && <button type="button" className="btn-ghost h-9" onClick={() => cancel.mutate(undefined)}><Ban size={14} />Cancel</button>}
          {canEdit && !active && <button type="button" className="btn-ghost h-9" onClick={() => retry.mutate(undefined)}><RotateCcw size={14} />Retry</button>}
        </div>
      </div>
      <div className="mt-5"><Bar value={job.progress} /></div>
      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-5">
        {COUNTER_LABELS.map(([k, label]) => (
          <div key={k} className={clsx('p-4 rounded-2xl border', k === 'high_priority' ? 'bg-lime border-lime text-ink' : 'bg-s2 border-line')}>
            <dt className={clsx('text-[11px]', k === 'high_priority' ? 'text-ink/70' : 'text-mute')}>{label}</dt>
            <dd className="num text-2xl mt-1">{job.counters?.[k] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {(job.errors?.length || job.warnings?.length) ? (
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {[['Errors', job.errors ?? [], 'text-danger'], ['Warnings', job.warnings ?? [], 'text-amber']].map(([title, items, cls]) => (
            (items as Job['warnings'])!.length ? (
              <div key={title as string}>
                <div className={clsx('eyebrow mb-2 flex items-center gap-1.5', cls as string)}><AlertTriangle size={12} />{title as string} ({(items as Job['warnings'])!.length})</div>
                <ul className="max-h-56 overflow-y-auto space-y-1.5 text-xs">
                  {(items as NonNullable<Job['warnings']>).slice().reverse().map((m, i) => (
                    <li key={i} className="p-2 rounded-xl bg-s2 border border-line"><span className="text-dim">{fmtDateTime(m.at)} · </span>{m.message}</li>
                  ))}
                </ul>
              </div>
            ) : null
          ))}
        </div>
      ) : null}
    </section>
  );
}
