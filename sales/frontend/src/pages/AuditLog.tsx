import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from '../services/api';
import { qs } from '../hooks/useCrm';
import { useMe } from '../hooks/useAuth';
import { PageHeader } from '../components/common/Card';
import { Select } from '../components/common/Form';
import { EmptyState } from '../components/common/Misc';
import { fmtDateTime } from '../utils/format';
import type { Paged } from '../types';

type Row = { id: number; action: string; entity_type: string | null; entity_id: string | null; meta: Record<string, unknown>; ip: string | null; user: string | null; created_at: string };

export default function AuditLog() {
  const admin = useMe().data?.role === 'ADMIN';
  const [action, setAction] = useState('');
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ['audit', action, page], enabled: admin, placeholderData: keepPreviousData,
    queryFn: () => api<Paged<Row> & { actions: string[] }>(`/audit${qs({ action, page, page_size: 50 })}`) });
  if (!admin) return <div><PageHeader title="Audit Log" /><EmptyState title="Admins only" body="Ask an admin if you need to review the audit log." /></div>;
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 50));
  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Sign-ins, changes, status moves, deletions, settings and exports. Secrets are never recorded."
        actions={<Select label="All actions" value={action} onChange={(v) => { setAction(v); setPage(1); }} options={q.data?.actions ?? []} />} />
      {q.isError && <p className="text-sm text-danger mb-3">{q.error.message}</p>}
      <div className="card overflow-x-auto">
        <table className="tbl w-full border-separate border-spacing-0">
          <thead><tr><th className="pl-5">When</th><th>User</th><th>Action</th><th>Record</th><th>Details</th><th>IP</th></tr></thead>
          <tbody>{(q.data?.items ?? []).map((r) => (
            <tr key={r.id}><td className="pl-5 text-xs">{fmtDateTime(r.created_at)}</td><td>{r.user ?? '—'}</td><td className="text-xs font-mono">{r.action}</td>
              <td className="text-xs text-mute">{r.entity_type ? `${r.entity_type} ${r.entity_id ?? ''}` : '—'}</td>
              <td className="text-xs text-mute whitespace-normal max-w-[420px] break-words font-mono">{Object.keys(r.meta).length ? JSON.stringify(r.meta) : ''}</td>
              <td className="text-xs text-dim">{r.ip ?? ''}</td></tr>))}</tbody>
        </table>
        {!q.isPending && !q.data?.items.length && <p className="text-sm text-mute p-6">No entries.</p>}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-line text-xs text-mute">
          <button type="button" className="icon-btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></button>
          <span className="num">{page} / {pages}</span>
          <button type="button" className="icon-btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}
