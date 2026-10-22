import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Pencil, Play, Plus, Radar, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useMe } from '../hooks/useAuth';
import { useCrmMutation } from '../hooks/useCrm';
import { ACTIVE, useJob, useProviders, useSearches, type Job, type Search } from '../hooks/useJobs';
import { useUi } from '../store/useUi';
import { PageHeader } from '../components/common/Card';
import { EmptyState, Skeleton } from '../components/common/Misc';
import { DiscoveryForm, type SearchDraft } from '../components/discovery/DiscoveryForm';
import { JobProgress, StatusPill } from '../components/discovery/JobProgress';
import { fmtDateTime } from '../utils/format';

export default function Discovery() {
  const [params, setParams] = useSearchParams();
  const jobId = Number(params.get('job')) || null;
  const [editing, setEditing] = useState<Search | 'new' | null>(params.get('new') ? 'new' : null);
  const canEdit = useMe().data?.can_edit;
  const ask = useUi((s) => s.ask);
  const searches = useSearches();
  const job = useJob(jobId);
  const providers = useProviders().data;
  const searchConfigured = !!providers?.providers.some((p) => p.kind === 'SEARCH' && p.state === 'CONFIGURED');
  const showJob = (j: Job) => setParams({ job: String(j.id) }, { replace: true });

  const run = useCrmMutation((id: number) => api<Job>(`/searches/${id}/run`, { body: {} }), { success: 'Discovery started', onSuccess: showJob });
  const save = useCrmMutation(async (d: SearchDraft & { id?: number }) => {
    const s = d.id ? await api<Search>(`/searches/${d.id}`, { method: 'PATCH', body: { name: d.name, criteria: d.criteria } })
      : await api<Search>('/searches', { body: d });
    return api<Job>(`/searches/${s.id}/run`, { body: {} });
  }, { success: 'Discovery started', onSuccess: (j) => { setEditing(null); showJob(j); } });
  const remove = useCrmMutation((id: number) => api(`/searches/${id}`, { method: 'DELETE' }), { success: 'Search deleted' });

  return (
    <div className="space-y-6">
      <PageHeader title="Discovery" subtitle="Find target companies, confirm their websites, and identify decision makers — with the source of everything."
        actions={canEdit && !editing && <button type="button" className="btn-primary" onClick={() => setEditing('new')}><Plus size={16} />New prospect search</button>} />

      {editing && (
        <DiscoveryForm key={editing === 'new' ? 'new' : editing.id} initial={editing === 'new' ? undefined : { name: editing.name, criteria: editing.criteria }}
          searchConfigured={searchConfigured} busy={save.isPending} onCancel={() => setEditing(null)}
          onSubmit={(d) => save.mutate({ ...d, id: editing === 'new' ? undefined : editing.id })} />
      )}

      {jobId && (job.isPending ? <Skeleton className="h-64" /> : job.data ? (
        <>
          <JobProgress job={job.data} canEdit={canEdit} onRetried={showJob} />
          {!!job.data.crawls?.length && (
            <section className="card overflow-x-auto" aria-label="Websites">
              <table className="tbl w-full border-separate border-spacing-0">
                <thead><tr><th className="pl-5">Company</th><th>Domain</th><th>Crawl</th><th>Pages</th><th>Robots</th><th>Issue</th></tr></thead>
                <tbody>{job.data.crawls.map((c) => (
                  <tr key={`${c.company_id}-${c.domain}`}><td className="pl-5"><Link to={`/companies/${c.company_id}`} className="hover:text-lime">{c.company}</Link></td>
                    <td className="text-mute">{c.domain}</td><td className="text-xs">{c.status}</td><td className="num">{c.pages_fetched}</td>
                    <td className="text-xs">{c.robots_allowed === null ? '—' : c.robots_allowed ? 'Allowed' : 'Disallowed'}</td>
                    <td className="text-xs text-danger whitespace-normal max-w-[360px]">{c.error ?? ''}</td></tr>))}</tbody>
              </table>
            </section>
          )}
          {!ACTIVE.includes(job.data.status) && <div className="flex gap-2"><Link to="/prospects?status=REVIEW" className="btn-primary">Review new prospects</Link><Link to="/companies" className="btn-ghost">Companies</Link></div>}
        </>
      ) : <p className="text-sm text-danger">Job not found.</p>)}

      <section aria-label="Saved searches">
        <div className="eyebrow mb-3">Saved searches</div>
        {searches.isPending ? <Skeleton className="h-32" /> : !searches.data?.length ? (
          <EmptyState icon={<Radar size={22} />} title="No searches yet" body="Create a prospect search to discover companies and decision makers."
            actions={canEdit ? <button type="button" className="btn-primary" onClick={() => setEditing('new')}><Plus size={16} />New prospect search</button> : undefined} />
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {searches.data.map((s) => {
              const last = s.last_job;
              const busy = !!last && ACTIVE.includes(last.status);
              return (
                <article key={s.id} className="card card-pad flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0"><h3 className="font-display text-lg truncate">{s.name}</h3>
                      <p className="text-xs text-mute">{[s.criteria.city, s.criteria.state, s.criteria.country].filter(Boolean).join(', ')} · up to {s.criteria.max_companies} companies{s.criteria.schedule ? ' · weekly' : ''}</p></div>
                    {last && <StatusPill status={last.status} />}
                  </div>
                  <p className="text-xs text-dim">{s.criteria.industries.join(', ') || 'Any industry'} · {s.criteria.departments.join(', ')}</p>
                  {last && <button type="button" className="text-left text-xs text-mute hover:text-fg" onClick={() => showJob(last)}>
                    Last run {fmtDateTime(last.created_at)} · {last.counters?.companies_discovered ?? 0} companies · {last.counters?.contacts_discovered ?? 0} contacts →</button>}
                  {canEdit && <div className="flex gap-2 mt-auto pt-2">
                    <button type="button" className="btn-primary h-9" disabled={busy || run.isPending} onClick={() => run.mutate(s.id)}><Play size={14} />{busy ? 'Running' : 'Run'}</button>
                    <button type="button" className="btn-ghost h-9" onClick={() => setEditing(s)}><Pencil size={14} />Edit & run</button>
                    <button type="button" className="icon-btn-sm ml-auto" aria-label={`Delete ${s.name}`} onClick={() => ask({ title: 'Delete search?', message: `"${s.name}" will be removed. Companies and contacts it found stay.`, confirmLabel: 'Delete', danger: true, onConfirm: () => remove.mutate(s.id) })}><Trash2 size={13} /></button>
                  </div>}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
