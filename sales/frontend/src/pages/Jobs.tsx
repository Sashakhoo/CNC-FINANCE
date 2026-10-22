import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Workflow } from 'lucide-react';
import { useMe } from '../hooks/useAuth';
import { useJob, useJobs, type Job } from '../hooks/useJobs';
import { PageHeader } from '../components/common/Card';
import { DataGrid } from '../components/common/DataGrid';
import { Drawer } from '../components/common/Overlay';
import { Bar, EmptyState } from '../components/common/Misc';
import { Select } from '../components/common/Form';
import { JobProgress, StatusPill, fmtDuration } from '../components/discovery/JobProgress';
import { fmtDateTime } from '../utils/format';

function JobDrawer({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const job = useJob(id);
  const canEdit = useMe().data?.can_edit;
  return (
    <Drawer open onClose={onClose} title={job.data?.name ?? 'Job'} subtitle={job.data ? `${job.data.job_type} · started by ${job.data.user ?? 'scheduler'}` : undefined} width="max-w-4xl">
      {job.data && <div className="space-y-5">
        <JobProgress job={job.data} canEdit={canEdit} onRetried={(j) => onOpen(j.id)} />
        {!!job.data.provider_calls?.length && <div className="card card-pad"><div className="eyebrow mb-2">Provider calls</div>
          <ul className="text-sm space-y-1">{job.data.provider_calls.map((p) => <li key={p.provider}>{p.provider}: <span className="num">{p.calls}</span> calls{p.errors ? <span className="text-danger"> · {p.errors} errors</span> : ''}</li>)}</ul></div>}
        {!!job.data.crawls?.length && <div className="card card-pad"><div className="eyebrow mb-2">Websites</div>
          <ul className="text-sm space-y-1">{job.data.crawls.map((c) => <li key={`${c.company_id}${c.domain}`}>{c.company} — {c.domain}: {c.pages_fetched} pages {c.error ? <span className="text-danger">({c.error})</span> : ''}</li>)}</ul></div>}
      </div>}
    </Drawer>
  );
}

export default function Jobs() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? '';
  const [page, setPage] = useState(1);
  const open = Number(params.get('open')) || null;
  const jobs = useJobs({ status: status || undefined, page, page_size: 25 });
  const columns = useMemo<ColumnDef<Job, unknown>[]>(() => [
    { id: 'name', header: 'Job', cell: ({ row: { original: j } }) => <div><div className="font-medium">{j.name}</div><div className="text-xs text-dim">{j.job_type} · #{j.id}</div></div> },
    { id: 'status', header: 'Status', cell: ({ row }) => <StatusPill status={row.original.status} /> },
    { id: 'provider', header: 'Provider', cell: ({ row }) => <span className="text-xs text-mute whitespace-normal max-w-[200px] inline-block">{row.original.provider ?? '—'}</span> },
    { id: 'started', header: 'Started', cell: ({ row }) => row.original.started_at ? fmtDateTime(row.original.started_at) : '—' },
    { id: 'duration', header: 'Duration', cell: ({ row }) => fmtDuration(row.original.duration_seconds) },
    { id: 'progress', header: 'Progress', cell: ({ row }) => <div className="w-28"><Bar value={row.original.progress} /></div> },
    { id: 'records', header: 'Processed / created', cell: ({ row }) => <span className="num">{row.original.records_processed} / {row.original.records_created}</span> },
    { id: 'issues', header: 'Issues', cell: ({ row: { original: j } }) => <span className="text-xs">{j.error_count ? <span className="text-danger">{j.error_count} errors</span> : null}{j.error_count && j.warning_count ? ' · ' : ''}{j.warning_count ? <span className="text-amber">{j.warning_count} warnings</span> : null}{!j.error_count && !j.warning_count ? '—' : ''}</span> },
  ], []);
  return (
    <div>
      <PageHeader title="Jobs" subtitle="Every background run with its real progress, provider, warnings and errors."
        actions={<Select label="All statuses" value={status} onChange={(v) => { setPage(1); setParams(v ? { status: v } : {}, { replace: true }); }} options={['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED']} />} />
      <DataGrid label="Jobs" data={jobs.data?.items ?? []} columns={columns} getId={(j) => String(j.id)} total={jobs.data?.total ?? 0}
        page={page} pageSize={25} onPage={setPage} loading={jobs.isPending}
        onRowClick={(j) => setParams((p) => { const n = new URLSearchParams(p); n.set('open', String(j.id)); return n; }, { replace: true })}
        empty={<EmptyState icon={<Workflow size={22} />} title="No jobs yet" body="Discovery runs, enrichment and scheduled refreshes appear here." />} />
      {open && <JobDrawer id={open} onOpen={(id) => setParams((p) => { const n = new URLSearchParams(p); n.set('open', String(id)); return n; }, { replace: true })} onClose={() => setParams((p) => { const n = new URLSearchParams(p); n.delete('open'); return n; }, { replace: true })} />}
    </div>
  );
}
