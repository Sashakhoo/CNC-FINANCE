import { useState } from 'react';
import clsx from 'clsx';
import { useSearchParams, Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, LayoutGrid, Rows3, Search, Users } from 'lucide-react';
import { useMe } from '../hooks/useAuth';
import { useMeta, useProspects } from '../hooks/useCrm';
import { useDebounced } from '../hooks/useDebounced';
import { Select } from '../components/common/Form';
import { EmptyState, Skeleton } from '../components/common/Misc';
import { WorkspaceCard } from '../components/crm/WorkspaceCard';
import Prospects from './Prospects';
import { statusLabel } from '../types';

const PAGE = 24;

function Workspace() {
  const [params, setParams] = useSearchParams();
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); if (k !== 'page') n.delete('page'); return n; }, { replace: true });
  const q = params.get('q') ?? '';
  const debounced = useDebounced(q);
  const status = params.get('status') ?? '';
  const page = Number(params.get('page') ?? 1);
  const canEdit = useMe().data?.can_edit;
  const meta = useMeta().data;
  // Soonest follow-up first; people with no follow-up come last.
  const list = useProspects({ q: debounced, status: status ? [status] : undefined, sort: 'follow_up_at', desc: false, page, page_size: PAGE });
  const items = list.data?.items ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE));

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <form role="search" className="relative w-full max-w-[560px]" onSubmit={(e) => e.preventDefault()}>
          <input type="search" aria-label="Search and filter contacts" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Search and filter…"
            className="w-full h-14 rounded-full bg-s2 border border-line pl-6 pr-16 text-sm outline-none focus:border-lime/60 placeholder:text-dim" />
          <span className="absolute right-1.5 top-1.5 w-11 h-11 rounded-full bg-fg text-bg flex items-center justify-center" aria-hidden><Search size={16} /></span>
        </form>
        <Select label="All stages" value={status} onChange={(v) => set('status', v)} options={(meta?.statuses ?? []).map((s) => ({ value: s, label: statusLabel(s) }))} />
      </div>
      {list.isError && <div role="alert" className="card card-pad text-danger text-sm mb-4">{list.error.message}</div>}
      {list.isPending ? (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-5">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[270px] rounded-[30px]" />)}</div>
      ) : !items.length ? (
        <EmptyState icon={<Users size={22} />} title="No contacts" body={q || status ? 'Nothing matches this search.' : 'Add decision makers from a company page, or run Discovery.'}
          actions={<Link to="/companies" className="btn-ghost">Go to Companies</Link>} />
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-5">
          {items.map((p, i) => <WorkspaceCard key={p.id} p={p} featured={i === 0 && page === 1} canEdit={canEdit} />)}
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-8 text-xs text-mute">
          <button type="button" className="icon-btn-sm" disabled={page <= 1} onClick={() => set('page', String(page - 1))} aria-label="Previous page"><ChevronLeft size={14} /></button>
          <span className="num">{page} / {pages}</span>
          <button type="button" className="icon-btn-sm" disabled={page >= pages} onClick={() => set('page', String(page + 1))} aria-label="Next page"><ChevronRight size={14} /></button>
        </div>
      )}
    </>
  );
}

export default function Contacts() {
  const [view, setView] = useState<'workspace' | 'table'>(() => {
    try { return (localStorage.getItem('contacts-view') as 'workspace' | 'table') || 'workspace'; } catch { return 'workspace'; }
  });
  const choose = (v: 'workspace' | 'table') => { setView(v); try { localStorage.setItem('contacts-view', v); } catch { /* ignore */ } };
  const toggle = (
    <div role="group" aria-label="View" className="flex p-1 rounded-full bg-s2 border border-line">
      {([['workspace', <LayoutGrid key="g" size={15} />, 'Workspace'], ['table', <Rows3 key="t" size={15} />, 'Table']] as const).map(([v, icon, label]) => (
        <button key={v} type="button" aria-pressed={view === v} onClick={() => choose(v)}
          className={clsx('h-8 px-3 rounded-full text-xs inline-flex items-center gap-1.5', view === v ? 'bg-fg text-bg' : 'text-mute hover:text-fg')}>{icon}{label}</button>
      ))}
    </div>
  );
  return (
    <div>
      {view === 'table' ? (
        <><div className="flex justify-end mb-2">{toggle}</div><Prospects key="contacts" mode="contacts" /></>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
            <h1 className="h-display text-5xl sm:text-[64px] leading-[1]">Works Space</h1>
            {toggle}
          </div>
          <Workspace />
        </>
      )}
    </div>
  );
}
