import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import type { ColumnDef, RowSelectionState } from '@tanstack/react-table';
import { Ban, Check, Download, Link2, Megaphone, Target, Upload, X } from 'lucide-react';
import { api } from '../services/api';
import { PageHeader } from '../components/common/Card';
import { DataGrid, type SortState } from '../components/common/DataGrid';
import { EmptyState } from '../components/common/Misc';
import { Chip, EmailBadge, MaybeScore, PriorityBadge, StatusBadge } from '../components/common/Badges';
import { SearchInput, Select } from '../components/common/Form';
import { SafeLink } from '../components/crm/Sources';
import { AddToCampaignModal } from '../components/crm/Outreach';
import { ImportWizard } from '../components/crm/ImportWizard';
import { useCrmMutation, useMeta, useProspects } from '../hooks/useCrm';
import { useMe } from '../hooks/useAuth';
import { useDebounced } from '../hooks/useDebounced';
import { useUi } from '../store/useUi';
import { shortName } from '../utils/format';
import { statusLabel, type Prospect, type ProspectStatus } from '../types';

const FILTERS = ['status', 'department', 'seniority', 'industry', 'state', 'email_status', 'priority', 'program', 'min_lead_score', 'min_confidence', 'min_match', 'size', 'source_type'] as const;
const SIZES = [{ value: '30-99', label: '30–99' }, { value: '100-249', label: '100–249' }, { value: '250-499', label: '250–499' }, { value: '500-1000', label: '500–1,000' }, { value: '1001-10000000', label: '1,000+' }];
const MINS = ['90', '80', '70', '60'].map((v) => ({ value: v, label: `${v}+` }));

export default function Prospects({ mode = 'prospects' }: { mode?: 'prospects' | 'contacts' }) {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const meta = useMeta().data;
  const canEdit = useMe().data?.can_edit;
  const ask = useUi((s) => s.ask);
  const toast = useUi((s) => s.toast);
  const get = (k: string) => params.get(k) ?? '';
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); if (k !== 'page') n.delete('page'); return n; }, { replace: true });
  const q = useDebounced(get('q'));
  const page = Number(get('page') || 1);
  const [size, setSize] = useState(50);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [campaigning, setCampaigning] = useState(false);
  const [importing, setImporting] = useState(false);
  const sort: SortState = { key: get('sort') || (mode === 'contacts' ? 'name' : 'lead_score'), desc: get('desc') ? get('desc') === 'true' : mode !== 'contacts' };
  const [smin, smax] = get('size') ? get('size').split('-') : ['', ''];

  const query = {
    q, status: get('status') ? [get('status')] : undefined, department: get('department') ? [get('department')] : undefined,
    seniority: get('seniority') ? [get('seniority')] : undefined, industry: get('industry') ? [get('industry')] : undefined,
    state: get('state') ? [get('state')] : undefined, email_status: get('email_status') ? [get('email_status')] : undefined,
    priority: get('priority') ? [get('priority')] : undefined, program: get('program') ? [get('program')] : undefined,
    source_type: get('source_type') ? [get('source_type')] : undefined,
    min_lead_score: get('min_lead_score') || undefined, min_confidence: get('min_confidence') || undefined, min_match: get('min_match') || undefined,
    size_min: smin || undefined, size_max: smax || undefined, sort: sort.key, desc: sort.desc, page, page_size: size,
  };
  const list = useProspects(query);
  const selectedIds = Object.keys(selection).map(Number);

  const bulk = useCrmMutation((b: { status: ProspectStatus }) => api<{ changed: number; skipped: { id: number; reason: string }[] }>('/contacts/bulk-status', { body: { ids: selectedIds, ...b } }), {
    success: (r) => `${r.changed} updated${r.skipped.length ? `, ${r.skipped.length} skipped` : ''}`,
    onSuccess: () => setSelection({}),
  });

  const exportUrl = (format: 'csv' | 'xlsx') => {
    const p = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => {
      if (['page', 'page_size', 'sort', 'desc'].includes(k) || v === undefined || v === '') return;
      if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x))); else p.set(k, String(v));
    });
    if (mode === 'contacts') p.delete('min_lead_score');
    p.set('format', format);
    return `/api/export/prospects?${p.toString()}`;
  };

  const columns = useMemo<ColumnDef<Prospect, unknown>[]>(() => {
    const cols: ColumnDef<Prospect, unknown>[] = [
      { id: 'name', header: 'Contact', meta: { sortable: true }, cell: ({ row: { original: p } }) => (
        <div className="min-w-0"><Link to={`/contacts/${p.id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:text-lime">{p.full_name}</Link>
          <div className="text-xs text-dim truncate max-w-[240px]">{p.original_title ?? 'Title unknown'}</div></div>) },
      { id: 'company', header: 'Company', meta: { sortable: true }, cell: ({ row: { original: p } }) => (
        <div><Link to={`/companies/${p.company.id}`} onClick={(e) => e.stopPropagation()} className="hover:text-lime">{shortName(p.company.display_name)}</Link>
          <div className="text-xs text-dim">{[p.company.industry, p.location?.state].filter(Boolean).join(' · ') || '—'}</div></div>) },
      { id: 'department', header: 'Dept', cell: ({ row }) => row.original.department ?? '—' },
      { id: 'email', header: 'Email', cell: ({ row: { original: p } }) => p.email ? <div><div className="text-xs break-all max-w-[220px] whitespace-normal">{p.email}</div>{p.email_status && <EmailBadge status={p.email_status} />}</div> : <span className="text-xs text-dim">None</span> },
      { id: 'profile', header: 'Profile', cell: ({ row }) => row.original.profile_url ? <span onClick={(e) => e.stopPropagation()}><SafeLink href={row.original.profile_url} className="text-lime inline-flex"><Link2 size={14} aria-label="Professional profile" /></SafeLink></span> : <span className="text-dim">—</span> },
      { id: 'status', header: 'Status', meta: { sortable: true }, cell: ({ row }) => <span className="inline-flex items-center gap-1.5"><StatusBadge status={row.original.status} />{row.original.suppressed && <Ban size={12} className="text-danger" aria-label="Do Not Contact" />}</span> },
    ];
    if (mode === 'prospects') {
      cols.splice(0, 0,
        { id: 'priority', header: 'Priority', cell: ({ row }) => row.original.priority ? <PriorityBadge priority={row.original.priority} /> : <span className="text-dim text-xs">—</span> },
        { id: 'lead_score', header: 'Lead', meta: { sortable: true }, cell: ({ row }) => <MaybeScore value={row.original.lead_score} title="Lead score" /> },
        { id: 'confidence', header: 'Confidence', meta: { sortable: true }, cell: ({ row }) => <MaybeScore value={row.original.contact_confidence} suffix="%" title="Contact confidence" /> });
      cols.push(
        { id: 'match', header: 'Training match', meta: { sortable: true }, cell: ({ row: { original: p } }) => p.training_program ? <div><div className="text-xs">{p.training_program}</div><MaybeScore value={p.match_score} suffix="%" title="Training match" /></div> : <span className="text-dim text-xs">—</span> },
        { id: 'sources', header: 'Sources', cell: ({ row }) => <span className="num text-xs text-mute">{row.original.source_count}</span> });
    } else {
      cols.push({ id: 'created_at', header: 'Added', meta: { sortable: true }, cell: ({ row }) => new Date(row.original.created_at).toLocaleDateString('en-GB') });
    }
    return cols;
  }, [mode]);

  const opts = (xs: string[] | undefined, label?: (s: string) => string) => (xs ?? []).map((x) => ({ value: x, label: label ? label(x) : x }));
  const active = FILTERS.filter((k) => get(k));

  return (
    <div>
      <PageHeader title={mode === 'contacts' ? 'Contacts' : 'Prospects'}
        subtitle={mode === 'contacts' ? 'Every decision maker in the CRM.' : 'Decision makers ranked by lead score. Contact confidence, training match and lead score are kept separate.'}
        actions={<>
          {canEdit && <button type="button" className="btn-ghost" onClick={() => setImporting(true)}><Upload size={15} />Import</button>}
          {canEdit && <a className="btn-ghost" href={exportUrl('csv')} download onClick={() => toast('Exporting — Do Not Contact rows are excluded', 'info')}><Download size={15} />CSV</a>}
          {canEdit && <a className="btn-ghost" href={exportUrl('xlsx')} download onClick={() => toast('Exporting — Do Not Contact rows are excluded', 'info')}><Download size={15} />XLSX</a>}
        </>} />
      <div className="space-y-3 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={get('q')} onChange={(v) => set('q', v)} placeholder="Search name, company or title" className="w-full sm:w-72" />
          <Select label="Status" value={get('status')} onChange={(v) => set('status', v)} options={opts(meta?.statuses, statusLabel)} />
          <Select label="Department" value={get('department')} onChange={(v) => set('department', v)} options={opts(meta?.departments)} />
          <Select label="Seniority" value={get('seniority')} onChange={(v) => set('seniority', v)} options={opts(meta?.seniorities)} />
          <Select label="Industry" value={get('industry')} onChange={(v) => set('industry', v)} options={opts(meta?.industries)} />
          <Select label="Location" value={get('state')} onChange={(v) => set('state', v)} options={opts(meta?.states)} />
          <Select label="Company size" value={get('size')} onChange={(v) => set('size', v)} options={SIZES} />
          <Select label="Email status" value={get('email_status')} onChange={(v) => set('email_status', v)} options={opts(meta?.email_statuses)} />
          {mode === 'prospects' && <>
            <Select label="Priority" value={get('priority')} onChange={(v) => set('priority', v)} options={opts(meta?.priorities)} />
            <Select label="Lead score" value={get('min_lead_score')} onChange={(v) => set('min_lead_score', v)} options={MINS} />
            <Select label="Confidence" value={get('min_confidence')} onChange={(v) => set('min_confidence', v)} options={MINS} />
            <Select label="Programme" value={get('program')} onChange={(v) => set('program', v)} options={(meta?.programs ?? []).map((p) => p.name)} />
            <Select label="Match %" value={get('min_match')} onChange={(v) => set('min_match', v)} options={MINS} />
            <Select label="Source" value={get('source_type')} onChange={(v) => set('source_type', v)} options={opts(meta?.source_types, (s) => s.replace(/_/g, ' ').toLowerCase())} />
          </>}
        </div>
        {active.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
            {active.map((k) => <Chip key={k} active onRemove={() => set(k, '')}>{k.replace(/_/g, ' ')}: {statusLabel(get(k))}</Chip>)}
            <button type="button" className="text-xs text-mute hover:text-fg hover:underline" onClick={() => setParams((p) => { const n = new URLSearchParams(p); FILTERS.forEach((k) => n.delete(k)); n.delete('page'); return n; }, { replace: true })}>Clear all</button>
          </div>
        )}
      </div>

      {canEdit && selectedIds.length > 0 && (
        <div className="card card-pad mb-4 flex flex-wrap items-center gap-2 py-3">
          <span className="text-sm">{selectedIds.length} selected</span>
          <button type="button" className="btn-primary h-9" onClick={() => bulk.mutate({ status: 'APPROVED' })} disabled={bulk.isPending}><Check size={14} />Approve</button>
          <button type="button" className="btn-ghost h-9" onClick={() => bulk.mutate({ status: 'REJECTED' })} disabled={bulk.isPending}><X size={14} />Reject</button>
          <button type="button" className="btn-danger h-9" disabled={bulk.isPending} onClick={() => ask({ title: `Mark ${selectedIds.length} as Do Not Contact?`, message: 'They and their emails go on the suppression list. Only an admin can undo this.', confirmLabel: 'Do Not Contact', danger: true, onConfirm: () => bulk.mutate({ status: 'DO_NOT_CONTACT' }) })}><Ban size={14} />Do not contact</button>
          <button type="button" className="btn-ghost h-9" onClick={() => setCampaigning(true)}><Megaphone size={14} />Add to campaign</button>
          <button type="button" className="btn-text h-9 ml-auto" onClick={() => setSelection({})}>Clear selection</button>
        </div>
      )}

      {list.isError && <div role="alert" className="card card-pad text-danger text-sm mb-4">{list.error.message}</div>}
      <DataGrid label={mode === 'contacts' ? 'Contacts' : 'Prospects'} data={list.data?.items ?? []} columns={columns} getId={(p) => String(p.id)}
        total={list.data?.total ?? 0} page={page} pageSize={size} onPage={(p) => set('page', String(p))} onPageSize={(n) => { setSize(n); set('page', ''); }}
        sort={sort} onSort={(s) => setParams((p) => { const n = new URLSearchParams(p); n.set('sort', s.key); n.set('desc', String(s.desc)); n.delete('page'); return n; }, { replace: true })}
        selectable={!!canEdit} selection={selection} onSelection={setSelection} onRowClick={(p) => nav(`/contacts/${p.id}`)} loading={list.isPending}
        empty={<EmptyState icon={<Target size={22} />} title="No prospects" body={active.length || get('q') ? 'Nothing matches these filters.' : 'Run Discovery or add decision makers from a company page.'}
          actions={<Link to="/companies" className="btn-ghost">Go to Companies</Link>} />} />
      {importing && <ImportWizard open onClose={() => setImporting(false)} />}
      {campaigning && <AddToCampaignModal contactIds={selectedIds} open onClose={() => { setCampaigning(false); setSelection({}); }} />}
    </div>
  );
}
