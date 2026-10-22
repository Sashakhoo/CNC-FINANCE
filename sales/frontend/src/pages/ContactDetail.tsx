import { useState } from 'react';
import clsx from 'clsx';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Ban, Check, Link2, Mail, Pencil, Plus, Receipt, Star, Trash2, X } from 'lucide-react';
import { api } from '../services/api';
import { useContact, useCrmMutation, useSetContact } from '../hooks/useCrm';
import { useMe } from '../hooks/useAuth';
import { useUi } from '../store/useUi';
import { ContactAvatar } from '../components/common/Avatar';
import { KV } from '../components/common/Card';
import { Modal } from '../components/common/Overlay';
import { ActivityTimeline, EmptyState, MatchRing, Skeleton } from '../components/common/Misc';
import { EmailBadge, PriorityBadge, ProvenanceBadge, ScoreBadge, StatusBadge } from '../components/common/Badges';
import { LogActivity, NotesPanel } from '../components/crm/Forms';
import { AddToCampaignModal, OutreachDrawer } from '../components/crm/Outreach';
import { SafeLink, SourceList, SourcesButton } from '../components/crm/Sources';
import { fmtDateTime, fmtRM } from '../utils/format';
import { STATUSES, statusLabel, type ContactDetail as Detail, type ProspectStatus, type ScoreFactor } from '../types';

const TABS = ['Emails & Profiles', 'Activities', 'Notes', 'Sources'] as const;

function Breakdown({ items }: { items: ScoreFactor[] }) {
  return (
    <ul className="mt-3 space-y-1.5">
      {items.map((f) => (
        <li key={f.factor} className="flex items-start justify-between gap-3 text-xs">
          <span className={f.met ? 'text-fg' : 'text-dim'}>{f.explanation}</span>
          <span className="num text-mute whitespace-nowrap">{f.points}/{f.max_points}</span>
        </li>
      ))}
    </ul>
  );
}

function ScoreCard({ title, question, children }: { title: string; question: string; children: React.ReactNode }) {
  return (
    <div className="card card-pad">
      <div className="eyebrow">{title}</div>
      <p className="text-xs text-dim mt-1">{question}</p>
      <div className="mt-4">{children}</div>
    </div>
  );
}

export default function ContactDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const q = useContact(id);
  const me = useMe().data;
  const setContact = useSetContact();
  const ask = useUi((s) => s.ask);
  const toast = useUi((s) => s.toast);
  const [tab, setTab] = useState<(typeof TABS)[number]>('Emails & Profiles');
  const [newEmail, setNewEmail] = useState('');
  const [newProfile, setNewProfile] = useState('');
  const [editing, setEditing] = useState<{ full_name: string; original_title: string; phone: string } | null>(null);
  const [wonOpen, setWonOpen] = useState(false);
  const [outreach, setOutreach] = useState(false);
  const [campaigning, setCampaigning] = useState(false);

  const onContact = (r: Detail) => setContact(r);
  const status = useCrmMutation((b: { status: ProspectStatus; note?: string }) => api<Detail>(`/contacts/${id}/status`, { body: b }), {
    success: (r) => r.invoice_error ? null : `Status: ${statusLabel(r.status)}`,
    onSuccess: (r) => {
      onContact(r);
      const extra = r as Detail & { invoice?: { invoice_number: string; amount: number } | null };
      if (extra.invoice) toast(`Invoice ${extra.invoice.invoice_number} raised in Finance`);
      if (r.invoice_error) toast(`Marked WON, but no invoice yet: ${r.invoice_error}`, 'warn');
    },
  });
  const retryInvoice = useCrmMutation(() => api<{ invoice: { invoice_number: string } | null; invoice_error: string | null }>(`/contacts/${id}/raise-invoice`, { body: {} }), {
    success: (r) => r.invoice ? `Invoice ${r.invoice.invoice_number} raised in Finance` : null,
    onSuccess: (r) => { if (r.invoice_error) toast(r.invoice_error, 'error'); },
  });
  const patch = useCrmMutation((b: Record<string, unknown>) => api<Detail>(`/contacts/${id}`, { method: 'PATCH', body: b }), { success: 'Saved', onSuccess: (r) => { onContact(r); setEditing(null); } });
  const addEmail = useCrmMutation(() => api<Detail>(`/contacts/${id}/emails`, { body: { email: newEmail } }), { success: 'Email added (unverified)', onSuccess: (r) => { onContact(r); setNewEmail(''); } });
  const addProfile = useCrmMutation(() => api<Detail>(`/contacts/${id}/profiles`, { body: { url: newProfile } }), { success: 'Profile added', onSuccess: (r) => { onContact(r); setNewProfile(''); } });
  const emailAction = useCrmMutation((a: { path: string; method: string }) => api<Detail>(a.path, { method: a.method, body: a.method === 'POST' ? {} : undefined }), { onSuccess: onContact });
  const del = useCrmMutation(() => api(`/contacts/${id}`, { method: 'DELETE' }), { success: 'Contact deleted', onSuccess: () => nav(-1) });
  const erase = useCrmMutation(() => api(`/contacts/${id}/erase`, { method: 'DELETE' }), { success: 'Contact permanently erased', onSuccess: () => nav('/prospects') });

  if (q.isPending) return <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-60" /></div>;
  if (q.isError) return <EmptyState title="Contact not available" body={q.error.message} actions={<Link to="/prospects" className="btn-ghost">Back to Prospects</Link>} />;
  const c = q.data;
  const edit = c.can_edit;
  const dnc = c.status === 'DO_NOT_CONTACT';
  const lockedDnc = dnc && me?.role !== 'ADMIN';
  const best = c.training_opportunities[0];
  const set = (s: ProspectStatus) => {
    if (s === 'WON') { setWonOpen(true); return; }
    if (s === 'DO_NOT_CONTACT') { ask({ title: 'Mark Do Not Contact?', message: `${c.full_name} and their emails go on the suppression list and can't be selected for outreach. Only an admin can undo this.`, confirmLabel: 'Do Not Contact', danger: true, onConfirm: () => status.mutate({ status: s }) }); return; }
    status.mutate({ status: s });
  };

  return (
    <div className="space-y-5">
      <button type="button" onClick={() => nav(-1)} className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-fg"><ArrowLeft size={15} />Back</button>

      {c.suppressed.length > 0 && <div role="alert" className="card card-pad border-danger/40 text-danger text-sm flex gap-2"><Ban size={16} />On the Do Not Contact list — excluded from outreach.</div>}

      <section className="card card-pad">
        <div className="flex flex-wrap items-start gap-5">
          <ContactAvatar name={c.full_name} size={64} />
          <div className="flex-1 min-w-[min(100%,260px)]">
            <h1 className="h-display text-3xl sm:text-4xl">{c.full_name}</h1>
            <p className="text-mute mt-1">{c.original_title ?? 'Title unknown'} · <Link to={`/companies/${c.company.id}`} className="text-lime hover:underline">{c.company.legal_name}</Link></p>
            <div className="flex flex-wrap items-center gap-3 mt-3"><StatusBadge status={c.status} /><span className="text-xs text-dim">since {c.status_changed_at ? fmtDateTime(c.status_changed_at) : '—'}</span></div>
          </div>
          <div className="flex flex-wrap gap-2">
            <SourcesButton sources={c.sources} title={c.full_name} />
            {edit && <button type="button" className="btn-ghost h-9" onClick={() => setEditing({ full_name: c.full_name, original_title: c.original_title ?? '', phone: c.phone ?? '' })}><Pencil size={14} />Edit</button>}
            {me?.role === 'ADMIN' && <button type="button" className="btn-danger h-9" onClick={() => ask({ title: 'Erase permanently?', message: `${c.full_name} and everything about them (emails, sources, notes, activity, drafts) will be permanently deleted. Their emails go on the Do Not Contact list so they aren't rediscovered. Use this for personal-data deletion requests. This can't be undone.`, confirmLabel: 'Erase permanently', danger: true, onConfirm: () => erase.mutate(undefined) })}>Erase</button>}
            {edit && <button type="button" className="btn-ghost h-9 text-danger" onClick={() => ask({ title: 'Delete contact?', message: `${c.full_name} will be removed from lists. This is logged in the audit log.`, confirmLabel: 'Delete', danger: true, onConfirm: () => del.mutate(undefined) })}><Trash2 size={14} />Delete</button>}
          </div>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-5 mt-6">
          <KV label="Normalized title">{c.normalized_title ?? <span className="text-dim">Not matched</span>}</KV>
          <KV label="Department">{c.department ?? '—'}</KV>
          <KV label="Seniority">{c.seniority ?? '—'}</KV>
          <KV label="Phone">{c.phone ?? <span className="text-dim">Unknown</span>}</KV>
          <KV label="Location">{c.company.location ? [c.company.location.city, c.company.location.state].filter(Boolean).join(', ') : <span className="text-dim">Unknown</span>}</KV>
        </div>

        {edit && (
          <div className="flex flex-wrap items-center gap-2 mt-6 pt-5 border-t border-line">
            {c.status === 'REVIEW' || c.status === 'NEW' ? <>
              <button type="button" className="btn-primary h-9" onClick={() => set('APPROVED')} disabled={status.isPending}><Check size={15} />Approve</button>
              <button type="button" className="btn-ghost h-9" onClick={() => set('REJECTED')} disabled={status.isPending}><X size={15} />Reject</button>
            </> : null}
            {!dnc && <button type="button" className="btn-ghost h-9" onClick={() => set('CONTACTED')} disabled={status.isPending || c.status === 'CONTACTED'}><Mail size={15} />Mark contacted</button>}
            {!dnc && <button type="button" className="btn-danger h-9" onClick={() => set('DO_NOT_CONTACT')} disabled={status.isPending}><Ban size={15} />Do not contact</button>}
            <label className="flex items-center gap-2 text-xs text-mute ml-auto">Pipeline
              <select aria-label="Pipeline status" className="h-9 rounded-full bg-s2 border border-line px-3 text-sm text-fg" value={c.status} disabled={lockedDnc || status.isPending}
                onChange={(e) => set(e.target.value as ProspectStatus)}>
                {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
              </select>
            </label>
            {lockedDnc && <span className="text-xs text-dim w-full">Only an admin can take a contact off Do Not Contact.</span>}
            <label className="flex items-center gap-2 text-xs text-mute">Follow-up
              <input type="date" className="h-9 rounded-full bg-s2 border border-line px-3 text-sm text-fg" value={c.follow_up_at?.slice(0, 10) ?? ''}
                onChange={(e) => patch.mutate({ follow_up_at: e.target.value ? new Date(`${e.target.value}T09:00:00`).toISOString() : null })} />
            </label>
            <button type="button" className="btn-primary h-9" onClick={() => setOutreach(true)}>Generate outreach</button>
            <button type="button" className="btn-ghost h-9" disabled={c.suppressed.length > 0} onClick={() => setCampaigning(true)}>Add to campaign</button>
          </div>
        )}
        {c.status === 'WON' && (
          <div className="mt-4 p-4 rounded-2xl bg-s2 border border-line flex flex-wrap items-center gap-3 text-sm">
            <Receipt size={16} className="text-lime" />
            {c.invoice ? <>Invoice <span className="num">{c.invoice.invoice_number}</span> ({fmtRM(c.invoice.amount)}) raised in Finance.</>
              : <>No Finance invoice yet. {edit && <button type="button" className="btn-ghost h-8" onClick={() => retryInvoice.mutate(undefined)} disabled={retryInvoice.isPending}>Raise invoice now</button>}</>}
          </div>
        )}
      </section>

      <div className="grid lg:grid-cols-3 gap-4">
        <ScoreCard title="Contact confidence" question="How sure are we this contact information is correct?">
          {c.contact_confidence ? <><ScoreBadge score={c.contact_confidence.score} size="lg" label="Contact confidence" /><Breakdown items={c.contact_confidence.breakdown} /></>
            : <p className="text-sm text-dim">Not calculated yet.</p>}
        </ScoreCard>
        <ScoreCard title="Training match" question="How well does the company fit a Codencode programme?">
          {best ? <div className="flex gap-4"><MatchRing value={best.match_score} size={72} /><div><div className="font-display">{best.program}</div><p className="text-xs text-mute mt-1">{best.reason}</p></div></div>
            : <p className="text-sm text-dim">No training match yet — run Analyze opportunity on the company.</p>}
        </ScoreCard>
        <ScoreCard title="Lead score" question="How valuable is this prospect?">
          {c.lead_score ? <><div className="flex items-center gap-3"><ScoreBadge score={c.lead_score.score} size="lg" /><PriorityBadge priority={c.lead_score.priority} /></div><Breakdown items={c.lead_score.breakdown} /></>
            : <p className="text-sm text-dim">Not calculated yet.</p>}
        </ScoreCard>
      </div>

      <div role="tablist" aria-label="Contact sections" className="flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={clsx('h-9 px-4 rounded-full text-sm whitespace-nowrap', tab === t ? 'bg-fg text-bg' : 'text-mute hover:text-fg hover:bg-s2')}>{t}</button>
        ))}
      </div>

      <section className="card card-pad" role="tabpanel" aria-label={tab}>
        {tab === 'Emails & Profiles' && (
          <div className="grid lg:grid-cols-2 gap-8">
            <div>
              <div className="eyebrow mb-3">Business emails</div>
              {!c.emails.length && <p className="text-sm text-mute mb-3">No email found yet.</p>}
              <ul className="space-y-2">{c.emails.map((e) => (
                <li key={e.id} className="p-3 rounded-2xl bg-s2 border border-line">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium break-all">{e.email}</span>
                    {e.is_primary && <span className="text-[10px] text-lime">PRIMARY</span>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-1.5">
                    <EmailBadge status={e.verification_status} /><ProvenanceBadge value={e.provenance} />
                    <span className="text-[11px] text-dim">{e.discovery_method.replace(/_/g, ' ').toLowerCase()} · {e.email_type.replace(/_/g, ' ').toLowerCase()}{e.verification_provider ? ` · verified by ${e.verification_provider}` : ''}</span>
                  </div>
                  {edit && <div className="flex gap-3 mt-2 text-[11px]">
                    {!e.is_primary && <button type="button" className="text-mute hover:text-fg inline-flex items-center gap-1" onClick={() => emailAction.mutate({ path: `/contacts/${id}/emails/${e.id}/primary`, method: 'POST' })}><Star size={11} />Make primary</button>}
                    <button type="button" className="text-mute hover:text-danger" onClick={() => emailAction.mutate({ path: `/contacts/${id}/emails/${e.id}`, method: 'DELETE' })}>Remove</button>
                  </div>}
                </li>))}</ul>
              {edit && <form className="flex gap-2 mt-3" onSubmit={(ev) => { ev.preventDefault(); if (newEmail.trim()) addEmail.mutate(undefined); }}>
                <input aria-label="New email" type="email" className="input" value={newEmail} onChange={(ev) => setNewEmail(ev.target.value)} placeholder="name@company.com" />
                <button type="submit" className="btn-ghost" disabled={!newEmail.trim()}><Plus size={14} />Add</button>
              </form>}
              <p className="text-xs text-dim mt-2">Manually added emails stay UNVERIFIED until a verification provider checks them (Find contacts on the company).</p>
            </div>
            <div>
              <div className="eyebrow mb-3">Professional profiles</div>
              {!c.profiles.length && <p className="text-sm text-mute mb-3">None found yet.</p>}
              <ul className="space-y-2">{c.profiles.map((p) => (
                <li key={p.id} className="p-3 rounded-2xl bg-s2 border border-line flex items-center gap-3">
                  <Link2 size={14} className="text-mute shrink-0" />
                  <SafeLink href={p.url} className="text-sm text-lime hover:underline break-all flex-1" />
                  <span className="text-[11px] text-dim">{p.source_type.replace(/_/g, ' ').toLowerCase()}</span>
                  {edit && <button type="button" className="text-[11px] text-mute hover:text-danger" onClick={() => emailAction.mutate({ path: `/contacts/${id}/profiles/${p.id}`, method: 'DELETE' })}>Remove</button>}
                </li>))}</ul>
              {edit && <form className="flex gap-2 mt-3" onSubmit={(ev) => { ev.preventDefault(); if (newProfile.trim()) addProfile.mutate(undefined); }}>
                <input aria-label="New profile URL" className="input" value={newProfile} onChange={(ev) => setNewProfile(ev.target.value)} placeholder="https://www.linkedin.com/in/…" />
                <button type="submit" className="btn-ghost" disabled={!newProfile.trim()}><Plus size={14} />Add</button>
              </form>}
              <p className="text-xs text-dim mt-2">Stored as a reference link only — profiles are never logged into or scraped.</p>
            </div>
          </div>
        )}
        {tab === 'Activities' && <>{edit && <LogActivity target={{ contact_id: c.id }} />}<ActivityTimeline items={c.activities} /></>}
        {tab === 'Notes' && <NotesPanel notes={c.notes} target={{ contact_id: c.id }} canEdit={edit} />}
        {tab === 'Sources' && <SourceList sources={c.sources} />}
      </section>

      <OutreachDrawer contactId={c.id} name={c.full_name} open={outreach} onClose={() => setOutreach(false)} canEdit={edit} blocked={c.suppressed.length > 0} />
      {campaigning && <AddToCampaignModal contactIds={[c.id]} open onClose={() => setCampaigning(false)} />}

      <Modal open={wonOpen} onClose={() => setWonOpen(false)} title="Mark this deal WON?" size="sm"
        footer={<>
          <button type="button" className="btn-ghost" onClick={() => setWonOpen(false)}>Cancel</button>
          <button type="button" className="btn-primary" disabled={!c.company.deal_value || status.isPending} onClick={() => { setWonOpen(false); status.mutate({ status: 'WON' }); }}>Mark WON & raise invoice</button>
        </>}>
        {c.company.deal_value
          ? <p className="text-sm text-mute">A Pending invoice for <span className="text-fg">{fmtRM(c.company.deal_value)}</span> will be raised in Finance for {c.company.legal_name}, attention {c.full_name}.</p>
          : <p className="text-sm text-amber flex gap-2"><AlertTriangle size={16} />Set a deal value on <Link className="underline" to={`/companies/${c.company.id}`}>the company</Link> first — the invoice amount comes from it.</p>}
      </Modal>

      <Modal open={!!editing} onClose={() => setEditing(null)} title="Edit contact" size="sm"
        footer={<><button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
          <button type="button" className="btn-primary" disabled={!editing?.full_name.trim() || patch.isPending} onClick={() => editing && patch.mutate({ full_name: editing.full_name, original_title: editing.original_title || null, phone: editing.phone || null })}>Save</button></>}>
        {editing && <div className="space-y-3">
          {(['full_name', 'original_title', 'phone'] as const).map((k) => (
            <label key={k} className="flex flex-col gap-1.5"><span className="label">{k === 'full_name' ? 'Full name' : k === 'original_title' ? 'Job title' : 'Phone'}</span>
              <input className="input" value={editing[k]} maxLength={200} onChange={(e) => setEditing({ ...editing, [k]: e.target.value })} /></label>
          ))}
        </div>}
      </Modal>
    </div>
  );
}
