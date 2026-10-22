import { useState } from 'react';
import clsx from 'clsx';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Globe, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useCompany, useCrmMutation } from '../hooks/useCrm';
import { useUi } from '../store/useUi';
import { useMe } from '../hooks/useAuth';
import { CompanyAvatar } from '../components/common/Avatar';
import { KV } from '../components/common/Card';
import { ActivityTimeline, EmptyState, MatchRing, Skeleton } from '../components/common/Misc';
import { PriorityBadge, ProvenanceBadge, StatusBadge } from '../components/common/Badges';
import { CompanyFormModal, ContactFormModal, LogActivity, NotesPanel } from '../components/crm/Forms';
import { SafeLink, SourceList, SourcesButton } from '../components/crm/Sources';
import { AddToCampaignModal } from '../components/crm/Outreach';
import { fmtDateTime, fmtNum, fmtRM } from '../utils/format';
import type { CompanyDetail as Detail } from '../types';

const TABS = ['Decision Makers', 'Training Opportunities', 'Signals', 'Activities', 'Notes', 'Sources', 'Crawl History', 'Invoices'] as const;

function Unknown() { return <span className="text-dim">Unknown</span>; }

export default function CompanyDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const q = useCompany(id);
  const [tab, setTab] = useState<(typeof TABS)[number]>('Decision Makers');
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [campaigning, setCampaigning] = useState(false);
  const ask = useUi((s) => s.ask);
  const del = useCrmMutation(() => api(`/companies/${id}`, { method: 'DELETE' }), { success: 'Company deleted', onSuccess: () => nav('/companies') });
  const admin = useMe().data?.role === 'ADMIN';
  const erase = useCrmMutation(() => api(`/companies/${id}/erase`, { method: 'DELETE' }), { success: 'Company permanently erased', onSuccess: () => nav('/companies') });
  const enrich = useCrmMutation((action: string) => api<{ id: number }>(`/companies/${id}/enrich?action=${action}`, { body: {} }),
    { success: 'Job started — opening the Job Monitor', onSuccess: (j) => nav(`/jobs?open=${j.id}`) });

  if (q.isPending) return <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-80" /></div>;
  if (q.isError) return <EmptyState title="Company not available" body={q.error.message} actions={<Link to="/companies" className="btn-ghost">Back to Companies</Link>} />;
  const c: Detail = q.data;
  const loc = c.location;

  return (
    <div className="space-y-5">
      <Link to="/companies" className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-fg"><ArrowLeft size={15} />Companies</Link>

      {c.suppressed.length > 0 && <div role="alert" className="card card-pad border-danger/40 text-danger text-sm flex gap-2"><AlertTriangle size={16} />This company is on the Do Not Contact list.</div>}
      {c.possible_duplicates.length > 0 && (
        <div className="card card-pad border-amber/40 text-sm flex flex-wrap gap-2 items-center"><AlertTriangle size={16} className="text-amber" />Possible duplicate of
          {c.possible_duplicates.map((d) => <Link key={d.other_id} to={`/companies/${d.other_id}`} className="text-lime hover:underline">#{d.other_id} ({Math.round(d.similarity * 100)}% similar)</Link>)}
          <span className="text-mute">— review before outreach. Records are never merged automatically.</span>
        </div>
      )}

      <section className="card card-pad">
        <div className="flex flex-wrap items-start gap-5">
          <CompanyAvatar name={c.display_name} size={64} />
          <div className="flex-1 min-w-[min(100%,260px)]">
            <h1 className="h-display text-3xl sm:text-4xl">{c.legal_name}</h1>
            <div className="flex flex-wrap items-center gap-3 mt-2 text-sm text-mute">
              {c.website ? <SafeLink href={c.website} className="inline-flex items-center gap-1.5 text-lime hover:underline"><Globe size={14} />{c.domain}</SafeLink> : <span>No website</span>}
              <span className="text-[11px] tracking-[0.08em] uppercase">Domain: {c.domain_status.replace('_', ' ').toLowerCase()}{c.domain_confidence !== null ? ` · ${Math.round(c.domain_confidence * 100)}%` : ''}</span>
              {c.is_demo && <span className="text-amber text-xs">DEMO RECORD</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <SourcesButton sources={c.sources} title={c.legal_name} />
            {c.can_edit && <button type="button" className="btn-ghost h-9" onClick={() => setEditing(true)}><Pencil size={14} />Edit</button>}
            {admin && <button type="button" className="btn-danger h-9" onClick={() => ask({ title: 'Erase company permanently?', message: `${c.legal_name}, its ${c.contacts.length} contacts and all their data will be permanently deleted, and its domain and emails go on the Do Not Contact list. This can't be undone.`, confirmLabel: 'Erase permanently', danger: true, onConfirm: () => erase.mutate(undefined) })}>Erase</button>}
            {c.can_edit && <button type="button" className="btn-ghost h-9 text-danger" onClick={() => ask({ title: 'Delete company?', message: `${c.legal_name} and its ${c.contacts.length} contacts will be hidden. This is logged in the audit log.`, confirmLabel: 'Delete', danger: true, onConfirm: () => del.mutate(undefined) })}><Trash2 size={14} />Delete</button>}
          </div>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mt-6">
          <KV label="Industry">{c.industry ?? <Unknown />}</KV>
          <KV label="Location">{loc ? [loc.city, loc.state, loc.country].filter(Boolean).join(', ') : <Unknown />}</KV>
          <KV label="Company size">{c.employee_estimate ? `${fmtNum(c.employee_estimate)} employees` : <Unknown />}</KV>
          <KV label="Deal value">{c.deal_value ? fmtRM(c.deal_value) : <span className="text-dim">Not set</span>}</KV>
          <KV label="Phone">{c.phone ?? <Unknown />}</KV>
          <KV label="General email">{c.general_email ?? <Unknown />}</KV>
          <KV label="Last crawled">{c.last_crawled_at ? fmtDateTime(c.last_crawled_at) : <span className="text-dim">Never</span>}</KV>
          <KV label="Last enriched">{c.last_enriched_at ? fmtDateTime(c.last_enriched_at) : <span className="text-dim">Never</span>}</KV>
        </div>
        {c.description && <p className="text-sm text-mute mt-5 max-w-3xl">{c.description}</p>}
        <div className="flex flex-wrap gap-2 mt-6 pt-5 border-t border-line">
          {c.can_edit && <>
            <button type="button" className="btn-ghost h-9" disabled={enrich.isPending || !c.website} title={c.website ? 'Crawl the website again and refresh everything' : 'Add a website first'} onClick={() => enrich.mutate('reenrich')}>Re-enrich</button>
            <button type="button" className="btn-ghost h-9" disabled={enrich.isPending || !c.website} title={c.website ? 'Look for decision makers, profiles and emails' : 'Add a website first'} onClick={() => enrich.mutate('find_contacts')}>Find contacts</button>
            <button type="button" className="btn-ghost h-9" disabled={enrich.isPending} title="Recalculate training match and scores from stored evidence" onClick={() => enrich.mutate('analyze')}>Analyze opportunity</button>
          </>}
          {c.can_edit && <button type="button" className="btn-ghost h-9" disabled={!c.contacts.length || c.suppressed.length > 0} title={c.contacts.length ? 'Add all decision makers to a campaign' : 'No decision makers yet'} onClick={() => setCampaigning(true)}>Add to campaign</button>}
        </div>
      </section>

      <div role="tablist" aria-label="Company sections" className="flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={clsx('h-9 px-4 rounded-full text-sm whitespace-nowrap', tab === t ? 'bg-fg text-bg' : 'text-mute hover:text-fg hover:bg-s2')}>{t}</button>
        ))}
      </div>

      <section className="card card-pad" role="tabpanel" aria-label={tab}>
        {tab === 'Decision Makers' && (
          <>
            <div className="flex justify-between items-center mb-4">
              <p className="text-sm text-mute">{c.contacts.length} people</p>
              {c.can_edit && <button type="button" className="btn-primary h-9" onClick={() => setAdding(true)}><Plus size={15} />Add decision maker</button>}
            </div>
            {!c.contacts.length ? <p className="text-sm text-mute">No decision makers yet.</p> : (
              <div className="overflow-x-auto"><table className="tbl w-full border-separate border-spacing-0">
                <thead><tr><th>Name</th><th>Title</th><th>Department</th><th>Seniority</th><th>Lead score</th><th>Status</th></tr></thead>
                <tbody>{c.contacts.map((p) => (
                  <tr key={p.id} className="cursor-pointer" tabIndex={0} onClick={() => nav(`/contacts/${p.id}`)} onKeyDown={(e) => e.key === 'Enter' && nav(`/contacts/${p.id}`)}>
                    <td className="font-medium">{p.full_name}</td>
                    <td className="text-mute">{p.original_title ?? '—'}{p.normalized_title && p.normalized_title !== p.original_title && <div className="text-[11px] text-dim">{p.normalized_title}</div>}</td>
                    <td>{p.department ?? '—'}</td><td>{p.seniority ?? '—'}</td>
                    <td>{p.lead_score !== null ? <span className="flex items-center gap-2"><span className="num">{p.lead_score}</span>{p.priority && <PriorityBadge priority={p.priority} />}</span> : <span className="text-dim text-xs">Not calculated</span>}</td>
                    <td><StatusBadge status={p.status} /></td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </>
        )}
        {tab === 'Training Opportunities' && (!c.training_opportunities.length
          ? <p className="text-sm text-mute">No training match yet. Use Analyze opportunity (needs crawled website evidence — Re-enrich first if the site hasn't been crawled).</p>
          : <div className="space-y-4">{c.training_opportunities.map((o) => (
            <div key={o.id} className="flex gap-5 p-4 rounded-2xl bg-s2 border border-line">
              <MatchRing value={o.match_score} size={80} />
              <div className="min-w-0">
                <div className="font-display text-lg">{o.program}</div>
                <p className="text-sm text-mute mt-1">{o.reason}</p>
                {o.recommended_decision_maker && <p className="text-xs text-dim mt-1">Talk to: {o.recommended_decision_maker}</p>}
                <ul className="mt-2 space-y-1">{o.evidence.map((e, i) => <li key={i} className="text-xs"><span className="italic text-mute">“{e.quote}”</span> <SafeLink href={e.source_url} className="text-lime hover:underline">source</SafeLink></li>)}</ul>
              </div>
            </div>))}</div>)}
        {tab === 'Signals' && (!c.signals.length ? <p className="text-sm text-mute">No signals detected yet. Re-enrich to crawl the website.</p> : (
          <ul className="space-y-3">{c.signals.map((s) => (
            <li key={s.id} className="p-4 rounded-2xl bg-s2 border border-line">
              <div className="flex flex-wrap items-center gap-2"><span className="label">{s.signal_type.replace(/_/g, ' ')}</span><ProvenanceBadge value={s.provenance} />{s.confidence !== null && <span className="text-[11px] text-dim">{Math.round(s.confidence * 100)}%</span>}</div>
              <div className="text-sm mt-1">{s.title}</div>
              {s.evidence && <blockquote className="text-xs text-mute mt-2 italic">“{s.evidence}”</blockquote>}
              {s.source_url && <SafeLink href={s.source_url} className="text-[11px] text-lime hover:underline break-all" />}
            </li>))}</ul>))}
        {tab === 'Activities' && <>{c.can_edit && <LogActivity target={{ company_id: c.id }} />}<ActivityTimeline items={c.activities} /></>}
        {tab === 'Notes' && <NotesPanel notes={c.notes} target={{ company_id: c.id }} canEdit={c.can_edit} />}
        {tab === 'Sources' && <SourceList sources={c.sources} />}
        {tab === 'Crawl History' && (!c.crawl_history.length ? <p className="text-sm text-mute">This website hasn't been crawled yet. Use Re-enrich.</p> : (
          <table className="tbl w-full border-separate border-spacing-0"><thead><tr><th>Started</th><th>Status</th><th>Pages</th><th>Robots</th><th>Error</th></tr></thead>
            <tbody>{c.crawl_history.map((j) => <tr key={j.id}><td>{j.started_at ? fmtDateTime(j.started_at) : '—'}</td><td>{j.status}</td><td>{j.pages_fetched} fetched · {j.pages_skipped} skipped</td><td>{j.robots_allowed === null ? '—' : j.robots_allowed ? 'Allowed' : 'Disallowed'}</td><td className="text-danger whitespace-normal">{j.error ?? ''}</td></tr>)}</tbody></table>))}
        {tab === 'Invoices' && (!c.invoices.length ? <p className="text-sm text-mute">No invoices yet. Marking a contact WON raises one in Finance.</p> : (
          <ul className="space-y-2">{c.invoices.map((i) => <li key={i.invoice_number} className="text-sm"><span className="num">{i.invoice_number}</span> · {fmtRM(i.amount)} · {fmtDateTime(i.created_at)}</li>)}</ul>))}
      </section>

      {editing && <CompanyFormModal open onClose={() => setEditing(false)} company={c} />}
      {campaigning && <AddToCampaignModal contactIds={c.contacts.filter((p) => p.status !== 'DO_NOT_CONTACT').map((p) => p.id)} open onClose={() => setCampaigning(false)} />}
      <ContactFormModal open={adding} onClose={() => setAdding(false)} companyId={c.id} companyName={c.legal_name} />
    </div>
  );
}
