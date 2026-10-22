import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { ColumnDef, RowSelectionState } from '@tanstack/react-table';
import { ArrowLeft, Megaphone, Plus, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useMe } from '../hooks/useAuth';
import { useCrmMutation, useMeta, useProspects } from '../hooks/useCrm';
import { useUi } from '../store/useUi';
import { PageHeader } from '../components/common/Card';
import { Modal } from '../components/common/Overlay';
import { DataGrid } from '../components/common/DataGrid';
import { EmptyState, Skeleton } from '../components/common/Misc';
import { EmailBadge, MaybeScore, StatusBadge } from '../components/common/Badges';
import { ContactAvatar } from '../components/common/Avatar';
import type { CampaignRow } from '../components/crm/Outreach';
import { fmtRM } from '../utils/format';
import type { Prospect } from '../types';

const STAGES: [string, string][] = [['prospects', 'Prospects'], ['approved', 'Approved'], ['contacted', 'Contacted'], ['replied', 'Replies'],
  ['meeting', 'Meetings'], ['proposal', 'Proposals'], ['won', 'Won'], ['lost', 'Lost']];

function CampaignForm({ initial, open, onClose }: { initial?: CampaignRow; open: boolean; onClose: () => void }) {
  const meta = useMeta().data;
  const nav = useNavigate();
  const [f, setF] = useState({ name: initial?.name ?? '', program_id: initial?.program_id ? String(initial.program_id) : '', description: initial?.description ?? '',
    start_date: initial?.start_date ?? '', status: initial?.status ?? 'DRAFT' });
  const save = useCrmMutation(() => {
    const body = { ...f, program_id: f.program_id ? Number(f.program_id) : null, start_date: f.start_date || null };
    return initial ? api<CampaignRow>(`/campaigns/${initial.id}`, { method: 'PATCH', body }) : api<CampaignRow>('/campaigns', { body });
  }, { success: initial ? 'Campaign updated' : 'Campaign created', onSuccess: (c) => { onClose(); if (!initial) nav(`/campaigns/${c.id}`); } });
  return (
    <Modal open={open} onClose={onClose} title={initial ? 'Edit campaign' : 'New campaign'}
      footer={<><button type="button" className="btn-ghost" onClick={onClose}>Cancel</button><button type="button" className="btn-primary" disabled={f.name.trim().length < 2 || save.isPending} onClick={() => save.mutate(undefined)}>Save</button></>}>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5 sm:col-span-2"><span className="label">Name</span><input className="input" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Johor Manufacturing — AI Productivity" /></label>
        <label className="flex flex-col gap-1.5"><span className="label">Programme</span><select className="input" value={f.program_id} onChange={(e) => setF({ ...f, program_id: e.target.value })}><option value="">None</option>{meta?.programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="flex flex-col gap-1.5"><span className="label">Status</span><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{['DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED'].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label className="flex flex-col gap-1.5"><span className="label">Start date</span><input type="date" className="input" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
        <label className="flex flex-col gap-1.5 sm:col-span-2"><span className="label">Description</span><textarea className="input h-20 py-2" value={f.description} maxLength={5000} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      </div>
    </Modal>
  );
}

export default function Campaigns() {
  const canEdit = useMe().data?.can_edit;
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ['campaigns'], queryFn: () => api<CampaignRow[]>('/campaigns') });
  return (
    <div>
      <PageHeader title="Campaigns" subtitle="Group approved prospects around a programme and track every stage to won revenue."
        actions={canEdit && <button type="button" className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} />New campaign</button>} />
      {q.isPending ? <Skeleton className="h-48" /> : !q.data?.length ? (
        <EmptyState icon={<Megaphone size={22} />} title="No campaigns yet" body="Create one, then add prospects from the Prospects page or a contact." />
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {q.data.map((c, i) => (
            <Link key={c.id} to={`/campaigns/${c.id}`} className={i === 0 ? 'card card-pad bg-lime border-lime text-ink' : 'card card-pad hover:border-line2'}>
              <div className="flex items-start justify-between gap-2"><h3 className="font-display text-xl leading-tight">{c.name}</h3><span className="text-[10px] font-semibold tracking-[0.08em] opacity-70">{c.status}</span></div>
              <p className="text-xs opacity-70 mt-1">{c.program ?? 'No programme'} · {c.owner ?? '—'}{c.start_date ? ` · from ${c.start_date}` : ''}</p>
              <dl className="grid grid-cols-4 gap-2 mt-5">
                {[['prospects', 'Prospects'], ['contacted', 'Contacted'], ['meeting', 'Meetings'], ['won', 'Won']].map(([k, l]) => (
                  <div key={k}><dt className="text-[10px] opacity-60">{l}</dt><dd className="num text-xl">{c.metrics[k] ?? 0}</dd></div>))}
              </dl>
              <div className="text-xs opacity-70 mt-3">Pipeline {fmtRM(c.metrics.pipeline_value ?? 0)} · Won {fmtRM(c.metrics.won_value ?? 0)}</div>
            </Link>
          ))}
        </div>
      )}
      {creating && <CampaignForm open onClose={() => setCreating(false)} />}
    </div>
  );
}

export function CampaignDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const canEdit = useMe().data?.can_edit;
  const ask = useUi((s) => s.ask);
  const [editing, setEditing] = useState(false);
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const q = useQuery({ queryKey: ['campaigns', id], queryFn: () => api<CampaignRow>(`/campaigns/${id}`) });
  const members = useProspects({ campaign_id: id, page, page_size: 50, sort: 'status', desc: false });
  const remove = useCrmMutation((ids: number[]) => api(`/campaigns/${id}/contacts/remove`, { body: { contact_ids: ids } }), { success: 'Removed from campaign', onSuccess: () => setSelection({}) });
  const del = useCrmMutation(() => api(`/campaigns/${id}`, { method: 'DELETE' }), { success: 'Campaign deleted', onSuccess: () => nav('/campaigns') });
  const columns = useMemo<ColumnDef<Prospect, unknown>[]>(() => [
    { id: 'name', header: 'Contact', cell: ({ row: { original: p } }) => <Link to={`/contacts/${p.id}`} className="flex items-center gap-2.5 hover:text-lime" onClick={(e) => e.stopPropagation()}><ContactAvatar name={p.full_name} size={30} /><span><span className="font-medium block">{p.full_name}</span><span className="text-xs text-dim">{p.original_title ?? '—'}</span></span></Link> },
    { id: 'company', header: 'Company', cell: ({ row }) => row.original.company.display_name },
    { id: 'email', header: 'Email', cell: ({ row }) => row.original.email_status ? <EmailBadge status={row.original.email_status} /> : <span className="text-dim text-xs">None</span> },
    { id: 'lead', header: 'Lead', cell: ({ row }) => <MaybeScore value={row.original.lead_score} title="Lead score" /> },
    { id: 'status', header: 'Status', cell: ({ row }) => <StatusBadge status={row.original.status} /> },
  ], []);
  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <EmptyState title="Campaign not available" body={q.error.message} actions={<Link to="/campaigns" className="btn-ghost">Back</Link>} />;
  const c = q.data;
  const ids = Object.keys(selection).map(Number);
  return (
    <div className="space-y-5">
      <Link to="/campaigns" className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-fg"><ArrowLeft size={15} />Campaigns</Link>
      <PageHeader eyebrow={`${c.status}${c.program ? ` · ${c.program}` : ''}`} title={c.name} subtitle={c.description || undefined}
        actions={canEdit && <><button type="button" className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>
          <button type="button" className="btn-ghost text-danger" onClick={() => ask({ title: 'Delete campaign?', message: 'Contacts stay in the CRM; only the campaign is removed.', confirmLabel: 'Delete', danger: true, onConfirm: () => del.mutate(undefined) })}><Trash2 size={14} />Delete</button></>} />
      <dl className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-10 gap-3">
        {STAGES.map(([k, l]) => <div key={k} className="card p-4"><dt className="text-[11px] text-mute">{l}</dt><dd className="num text-2xl mt-1">{c.metrics[k] ?? 0}</dd></div>)}
        <div className="card p-4"><dt className="text-[11px] text-mute">Response rate</dt><dd className="num text-2xl mt-1">{c.metrics.response_rate === null ? '—' : `${c.metrics.response_rate}%`}</dd></div>
        <div className="card p-4 bg-lime border-lime text-ink"><dt className="text-[11px] text-ink/70">Pipeline</dt><dd className="num text-xl mt-1">{fmtRM(c.metrics.pipeline_value ?? 0)}</dd></div>
      </dl>
      {canEdit && ids.length > 0 && <div className="card card-pad py-3 flex items-center gap-3"><span className="text-sm">{ids.length} selected</span>
        <button type="button" className="btn-ghost h-9" onClick={() => remove.mutate(ids)}>Remove from campaign</button></div>}
      <DataGrid label="Campaign members" data={members.data?.items ?? []} columns={columns} getId={(p) => String(p.id)} total={members.data?.total ?? 0}
        page={page} pageSize={50} onPage={setPage} selectable={!!canEdit} selection={selection} onSelection={setSelection} loading={members.isPending}
        onRowClick={(p) => nav(`/contacts/${p.id}`)}
        empty={<EmptyState title="No prospects in this campaign" body="Add prospects from the Prospects page (select rows → Add to campaign) or from a contact." actions={<Link to="/prospects?status=APPROVED" className="btn-ghost">Approved prospects</Link>} />} />
      {editing && <CampaignForm initial={c} open onClose={() => setEditing(false)} />}
    </div>
  );
}
