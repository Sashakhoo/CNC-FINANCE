import { useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Activity, Briefcase, ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from '../services/api';
import { qs, useMeta } from '../hooks/useCrm';
import { PageHeader } from '../components/common/Card';
import { EmptyState, MatchRing, Skeleton } from '../components/common/Misc';
import { ProvenanceBadge } from '../components/common/Badges';
import { Select } from '../components/common/Form';
import { SafeLink } from '../components/crm/Sources';
import { fmtDate } from '../utils/format';
import type { Opportunity, Paged, Signal } from '../types';

function Pager({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-3 mt-6 text-xs text-mute">
      <button type="button" className="icon-btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></button>
      <span className="num">{page} / {pages}</span>
      <button type="button" className="icon-btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></button>
    </div>
  );
}

type SignalRow = Signal & { company: { id: number; name: string } };

export function Signals() {
  const [type, setType] = useState('');
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ['signals', type, page], placeholderData: keepPreviousData,
    queryFn: () => api<Paged<SignalRow> & { types: { type: string; count: number }[] }>(`/signals${qs({ signal_type: type, page, page_size: 30 })}`) });
  return (
    <div>
      <PageHeader title="Signals" subtitle="Buying signals detected on company websites — each with the exact sentence and page it came from."
        actions={<Select label="All signal types" value={type} onChange={(v) => { setType(v); setPage(1); }} options={(q.data?.types ?? []).map((t) => ({ value: t.type, label: `${t.type.replace(/_/g, ' ').toLowerCase()} (${t.count})` }))} />} />
      {q.isPending ? <Skeleton className="h-64" /> : !q.data?.items.length ? (
        <EmptyState icon={<Activity size={22} />} title="No signals yet" body="Signals appear after Discovery crawls company websites." actions={<Link to="/discovery" className="btn-ghost">Go to Discovery</Link>} />
      ) : (
        <ul className="grid md:grid-cols-2 gap-4">
          {q.data.items.map((s) => (
            <li key={s.id} className="card card-pad">
              <div className="flex flex-wrap items-center gap-2"><span className="label">{s.signal_type.replace(/_/g, ' ')}</span><ProvenanceBadge value={s.provenance} />
                {s.confidence !== null && <span className="text-[11px] text-dim">{Math.round(s.confidence * 100)}% confidence</span>}</div>
              <Link to={`/companies/${s.company.id}`} className="font-display text-lg mt-1 block hover:text-lime">{s.company.name}</Link>
              <div className="text-sm">{s.title}</div>
              {s.evidence && <blockquote className="text-xs text-mute mt-2 pl-3 border-l-2 border-line2 italic">“{s.evidence}”</blockquote>}
              <div className="flex flex-wrap gap-3 text-[11px] text-dim mt-2">{s.source_url && <SafeLink href={s.source_url} className="text-lime hover:underline break-all" />}
                {s.source_date && <span>Dated {fmtDate(s.source_date)}</span>}{s.discovered_at && <span>Found {fmtDate(s.discovered_at)}</span>}</div>
            </li>
          ))}
        </ul>
      )}
      <Pager page={page} total={q.data?.total ?? 0} size={30} onPage={setPage} />
    </div>
  );
}

type OppRow = Opportunity & { company: { id: number; name: string; industry: string | null } };

export function Opportunities() {
  const meta = useMeta().data;
  const [program, setProgram] = useState('');
  const [min, setMin] = useState('60');
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ['opportunities', program, min, page], placeholderData: keepPreviousData,
    queryFn: () => api<Paged<OppRow>>(`/opportunities${qs({ program, min_match: min || 0, page, page_size: 24 })}`) });
  return (
    <div>
      <PageHeader title="Opportunities" subtitle="Training match per company and programme, backed by quotes from their own website."
        actions={<>
          <Select label="All programmes" value={program} onChange={(v) => { setProgram(v); setPage(1); }} options={(meta?.programs ?? []).map((p) => p.name)} />
          <Select label="Any match" value={min} onChange={(v) => { setMin(v); setPage(1); }} options={['80', '70', '60', '40'].map((v) => ({ value: v, label: `${v}%+ match` }))} />
        </>} />
      {q.isPending ? <Skeleton className="h-64" /> : !q.data?.items.length ? (
        <EmptyState icon={<Briefcase size={22} />} title="No training opportunities" body="Opportunities are calculated from crawled website evidence after Discovery or Analyze opportunity." actions={<Link to="/discovery" className="btn-ghost">Go to Discovery</Link>} />
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {q.data.items.map((o) => (
            <article key={o.id} className="card card-pad">
              <div className="flex gap-4"><MatchRing value={o.match_score} size={76} />
                <div className="min-w-0"><div className="eyebrow">{o.program}</div><Link to={`/companies/${o.company.id}`} className="font-display text-lg hover:text-lime block truncate">{o.company.name}</Link>
                  <div className="text-xs text-dim">{o.company.industry ?? 'Industry unknown'}{o.recommended_decision_maker ? ` · talk to ${o.recommended_decision_maker}` : ''}</div></div></div>
              <p className="text-sm text-mute mt-3">{o.reason}</p>
              <ul className="mt-2 space-y-1">{o.evidence.slice(0, 2).map((e, i) => <li key={i} className="text-xs"><span className="italic text-mute">“{e.quote}”</span> {e.source_url && <SafeLink href={e.source_url} className="text-lime hover:underline">source</SafeLink>}</li>)}</ul>
              <div className="text-[10px] text-dim mt-2">{o.method === 'LLM' ? 'AI-assisted, quotes verified against the page' : 'Rule-based'}</div>
            </article>
          ))}
        </div>
      )}
      <Pager page={page} total={q.data?.total ?? 0} size={24} onPage={setPage} />
    </div>
  );
}
