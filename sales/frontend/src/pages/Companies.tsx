import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Building2, Plus, Upload } from 'lucide-react';
import { PageHeader } from '../components/common/Card';
import { DataGrid, type SortState } from '../components/common/DataGrid';
import { CompanyAvatar } from '../components/common/Avatar';
import { EmptyState } from '../components/common/Misc';
import { SearchInput, Select } from '../components/common/Form';
import { CompanyFormModal } from '../components/crm/Forms';
import { ImportWizard } from '../components/crm/ImportWizard';
import { useCompanies, useMeta } from '../hooks/useCrm';
import { useMe } from '../hooks/useAuth';
import { useDebounced } from '../hooks/useDebounced';
import { fmtNum, fmtRM, shortName } from '../utils/format';
import type { CompanySummary } from '../types';

export default function Companies() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); if (k !== 'page') n.delete('page'); return n; }, { replace: true });
  const q = params.get('q') ?? '';
  const debouncedQ = useDebounced(q);
  const sort: SortState = { key: params.get('sort') ?? 'name', desc: params.get('desc') === 'true' };
  const page = Number(params.get('page') ?? 1);
  const [size, setSize] = useState(25);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const meta = useMeta().data;
  const canEdit = useMe().data?.can_edit;
  const list = useCompanies({ q: debouncedQ, industry: params.get('industry') ?? '', state: params.get('state') ?? '', sort: sort.key, desc: sort.desc, page, page_size: size });

  const columns = useMemo<ColumnDef<CompanySummary, unknown>[]>(() => [
    { id: 'name', header: 'Company', meta: { sortable: true }, cell: ({ row: { original: c } }) => (
      <div className="flex items-center gap-3"><CompanyAvatar name={c.display_name} size={32} /><div className="min-w-0"><div className="font-medium truncate max-w-[280px]">{shortName(c.display_name)}</div><div className="text-xs text-dim">{c.domain ?? 'No website'}</div></div></div>
    ) },
    { id: 'industry', header: 'Industry', meta: { sortable: true }, cell: ({ row }) => row.original.industry ?? <span className="text-dim">Unknown</span> },
    { id: 'location', header: 'Location', cell: ({ row }) => row.original.location ? [row.original.location.city, row.original.location.state].filter(Boolean).join(', ') : <span className="text-dim">Unknown</span> },
    { id: 'employees', header: 'Employees', meta: { sortable: true }, cell: ({ row }) => row.original.employee_estimate ? fmtNum(row.original.employee_estimate) : <span className="text-dim">Unknown</span> },
    { id: 'contacts', header: 'Contacts', cell: ({ row }) => <span className="num">{row.original.contact_count ?? 0}</span> },
    { id: 'deal_value', header: 'Deal value', meta: { sortable: true }, cell: ({ row }) => row.original.deal_value ? fmtRM(row.original.deal_value) : <span className="text-dim">—</span> },
    { id: 'created_at', header: 'Added', meta: { sortable: true }, cell: ({ row }) => new Date(row.original.created_at).toLocaleDateString('en-GB') },
  ], []);

  return (
    <div>
      <PageHeader title="Companies" subtitle="Organisations you are prospecting. Every field shows its source on the company page."
        actions={canEdit && <><button type="button" className="btn-ghost" onClick={() => setImporting(true)}><Upload size={15} />Import</button>
          <button type="button" className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} />Add company</button></>} />
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <SearchInput value={q} onChange={(v) => set('q', v)} placeholder="Search name or domain" className="w-full sm:w-72" />
        <Select label="Industry" value={params.get('industry') ?? ''} onChange={(v) => set('industry', v)} options={meta?.industries ?? []} />
        <Select label="State" value={params.get('state') ?? ''} onChange={(v) => set('state', v)} options={meta?.states ?? []} />
      </div>
      {list.isError && <div role="alert" className="card card-pad text-danger text-sm mb-4">{list.error.message}</div>}
      <DataGrid label="Companies" data={list.data?.items ?? []} columns={columns} getId={(c) => String(c.id)} total={list.data?.total ?? 0}
        page={page} pageSize={size} onPage={(p) => set('page', String(p))} onPageSize={(n) => { setSize(n); set('page', ''); }}
        sort={sort} onSort={(s) => setParams((p) => { const n = new URLSearchParams(p); n.set('sort', s.key); n.set('desc', String(s.desc)); n.delete('page'); return n; }, { replace: true })}
        onRowClick={(c) => nav(`/companies/${c.id}`)} loading={list.isPending}
        empty={<EmptyState icon={<Building2 size={22} />} title="No companies" body={q || params.get('industry') || params.get('state') ? 'Nothing matches these filters.' : 'Run Discovery to find companies, or add one manually.'}
          actions={canEdit && !q ? <button type="button" className="btn-primary" onClick={() => setAdding(true)}><Plus size={16} />Add company</button> : undefined} />} />
      <CompanyFormModal open={adding} onClose={() => setAdding(false)} />
      {importing && <ImportWizard open onClose={() => setImporting(false)} />}
    </div>
  );
}
