import { useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { Check, Copy, Megaphone, Plus, Send, Sparkles, Trash2 } from 'lucide-react';
import { api } from '../../services/api';
import { useCrmMutation, useMeta } from '../../hooks/useCrm';
import { useProviders } from '../../hooks/useJobs';
import { useUi } from '../../store/useUi';
import { Drawer, Modal } from '../common/Overlay';
import { SafeLink } from './Sources';

export interface DraftRow { id: number; contact_id: number; campaign_id: number | null; channel: string; tone: string; subject: string; body: string; evidence: { source_url: string | null; quote: string }[]; generated_by: string; status: string; created_at: string; note?: string }
export interface CampaignRow { id: number; name: string; program: string | null; program_id: number | null; status: string; description: string; start_date: string | null; owner: string | null; metrics: Record<string, number | null> }

const CHANNELS = [['EMAIL', 'Email'], ['LINKEDIN', 'LinkedIn-style message'], ['FOLLOWUP', 'Follow-up']] as const;
const TONES = ['Professional', 'Friendly', 'Concise', 'Consultative'] as const;

function DraftCard({ d, canEdit }: { d: DraftRow; canEdit: boolean }) {
  const toast = useUi((s) => s.toast);
  const [subject, setSubject] = useState(d.subject);
  const [body, setBody] = useState(d.body);
  const dirty = subject !== d.subject || body !== d.body;
  const save = useCrmMutation(() => api(`/drafts/${d.id}`, { method: 'PATCH', body: { subject, body } }), { success: 'Draft saved' });
  const approve = useCrmMutation(() => api(`/drafts/${d.id}/approve`, { body: {} }), { success: 'Draft approved' });
  const sent = useCrmMutation(() => api(`/drafts/${d.id}/mark-sent`, { body: {} }), { success: 'Recorded as sent' });
  const del = useCrmMutation(() => api(`/drafts/${d.id}`, { method: 'DELETE' }), { success: 'Draft deleted' });
  const copy = async () => {
    try { await navigator.clipboard.writeText(d.channel === 'LINKEDIN' ? body : `Subject: ${subject}\n\n${body}`); toast('Copied to clipboard'); }
    catch { toast('Copy failed — select the text manually', 'error'); }
  };
  const locked = d.status === 'SENT' || !canEdit;
  return (
    <article className="p-4 rounded-2xl bg-s2 border border-line space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="label">{CHANNELS.find(([v]) => v === d.channel)?.[1] ?? d.channel}</span>
        <span className="text-dim">{d.tone} · {d.generated_by === 'LLM' ? 'AI-assisted' : 'template'} · {new Date(d.created_at).toLocaleString('en-GB')}</span>
        <span className={clsx('ml-auto h-5 px-2 rounded-full border inline-flex items-center font-semibold tracking-[0.06em]',
          d.status === 'APPROVED' ? 'bg-lime text-ink border-lime' : d.status === 'SENT' ? 'text-mute border-line' : 'text-amber border-amber/40')}>{d.status}</span>
      </div>
      {d.channel !== 'LINKEDIN' && <input aria-label="Subject" className="input" value={subject} disabled={locked} maxLength={300} onChange={(e) => setSubject(e.target.value)} />}
      <textarea aria-label="Message" className="input h-48 py-2 leading-relaxed" value={body} disabled={locked} maxLength={5000} onChange={(e) => setBody(e.target.value)} />
      {d.channel === 'LINKEDIN' && <p className={clsx('text-[11px]', body.length > 300 ? 'text-danger' : 'text-dim')}>{body.length}/300 characters</p>}
      {d.note && <p className="text-[11px] text-amber">{d.note}</p>}
      <div>
        <div className="label mb-1">Evidence used</div>
        {d.evidence.length ? <ul className="space-y-1">{d.evidence.map((e, i) => <li key={i} className="text-xs text-mute"><span className="italic">“{e.quote}”</span> {e.source_url && <SafeLink href={e.source_url} className="text-lime hover:underline">source</SafeLink>}</li>)}</ul>
          : <p className="text-xs text-dim">No company evidence — the draft is generic. Run Discovery or Analyze opportunity for a specific message.</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost h-9" onClick={copy}><Copy size={14} />Copy</button>
        {canEdit && d.status !== 'SENT' && <>
          <button type="button" className="btn-ghost h-9" disabled={!dirty || save.isPending} onClick={() => save.mutate(undefined)}>Save draft</button>
          {d.status !== 'APPROVED' && <button type="button" className="btn-primary h-9" disabled={dirty || approve.isPending} title={dirty ? 'Save first' : undefined} onClick={() => approve.mutate(undefined)}><Check size={14} />Approve</button>}
          {d.status === 'APPROVED' && <button type="button" className="btn-dark h-9" disabled={sent.isPending} onClick={() => sent.mutate(undefined)} aria-describedby={`sent-hint-${d.id}`}><Send size={14} />Mark as sent</button>}
          <button type="button" className="icon-btn-sm ml-auto" aria-label="Delete draft" onClick={() => del.mutate(undefined)}><Trash2 size={13} /></button>
        </>}
      </div>
      {d.status === 'APPROVED' && <p id={`sent-hint-${d.id}`} className="text-[11px] text-dim">Send it from your own email or LinkedIn, then press Mark as sent — the app never sends messages.</p>}
    </article>
  );
}

export function OutreachDrawer({ contactId, name, open, onClose, canEdit, blocked }: { contactId: number; name: string; open: boolean; onClose: () => void; canEdit: boolean; blocked: boolean }) {
  const [channel, setChannel] = useState<string>('EMAIL');
  const [tone, setTone] = useState<string>('Professional');
  const [useAi, setUseAi] = useState(false);
  const aiReady = !!useProviders().data?.providers.some((p) => p.kind === 'AI' && p.state === 'CONFIGURED');
  const drafts = useQuery({ queryKey: ['drafts', contactId], enabled: open, queryFn: () => api<DraftRow[]>(`/contacts/${contactId}/drafts`) });
  const gen = useCrmMutation(() => api<DraftRow>(`/contacts/${contactId}/drafts`, { body: { channel, tone, use_ai: useAi && aiReady } }),
    { success: 'Draft generated', onSuccess: () => drafts.refetch() });
  return (
    <Drawer open={open} onClose={onClose} title="Outreach" subtitle={`${name} · drafts are never sent automatically`} width="max-w-2xl">
      {blocked ? <p className="text-sm text-danger">This contact is on the Do Not Contact list.</p> : canEdit && (
        <div className="card card-pad mb-5 space-y-3">
          <div role="radiogroup" aria-label="Channel" className="flex flex-wrap gap-2">{CHANNELS.map(([v, l]) => (
            <button key={v} type="button" role="radio" aria-checked={channel === v} onClick={() => setChannel(v)} className={clsx('h-9 px-4 rounded-full text-xs border', channel === v ? 'bg-fg text-bg border-fg' : 'bg-s2 border-line text-mute hover:text-fg')}>{l}</button>))}</div>
          <div role="radiogroup" aria-label="Tone" className="flex flex-wrap gap-2">{TONES.map((t) => (
            <button key={t} type="button" role="radio" aria-checked={tone === t} onClick={() => setTone(t)} className={clsx('h-9 px-4 rounded-full text-xs border', tone === t ? 'bg-lime text-ink border-lime' : 'bg-s2 border-line text-mute hover:text-fg')}>{t}</button>))}</div>
          <label className={clsx('flex items-center gap-2 text-xs', aiReady ? 'text-mute' : 'text-dim')} title={aiReady ? undefined : 'No LLM provider configured'}>
            <input type="checkbox" checked={useAi && aiReady} disabled={!aiReady} onChange={(e) => setUseAi(e.target.checked)} />
            <Sparkles size={13} />Use AI (facts are checked against the evidence; falls back to the template){aiReady ? '' : ' — not configured'}
          </label>
          <button type="button" className="btn-primary" disabled={gen.isPending} onClick={() => gen.mutate(undefined)}><Plus size={15} />{gen.isPending ? 'Generating…' : 'Generate draft'}</button>
        </div>
      )}
      <div className="space-y-4">
        {drafts.data?.map((d) => <DraftCard key={d.id} d={d} canEdit={canEdit} />)}
        {drafts.data && !drafts.data.length && <p className="text-sm text-mute">No drafts yet.</p>}
      </div>
    </Drawer>
  );
}

export function AddToCampaignModal({ contactIds, open, onClose }: { contactIds: number[]; open: boolean; onClose: () => void }) {
  const meta = useMeta().data;
  const toast = useUi((s) => s.toast);
  const campaigns = useQuery({ queryKey: ['campaigns'], enabled: open, queryFn: () => api<CampaignRow[]>('/campaigns') });
  const [choice, setChoice] = useState<string>('');
  const [newName, setNewName] = useState('');
  const [program, setProgram] = useState('');
  const add = useCrmMutation(async () => {
    let id = Number(choice);
    if (choice === 'new') {
      const c = await api<CampaignRow>('/campaigns', { body: { name: newName.trim(), program_id: program ? Number(program) : null, status: 'ACTIVE' } });
      id = c.id;
    }
    return api<{ added: number; skipped: { id: number; reason: string }[] }>(`/campaigns/${id}/contacts`, { body: { contact_ids: contactIds } });
  }, { onSuccess: (r) => { toast(`${r.added} added${r.skipped.length ? `, ${r.skipped.length} skipped (${[...new Set(r.skipped.map((s) => s.reason))].join(', ')})` : ''}`, r.added ? 'ok' : 'warn'); onClose(); } });
  const ok = choice && (choice !== 'new' || newName.trim().length >= 2);
  return (
    <Modal open={open} onClose={onClose} title="Add to campaign" subtitle={`${contactIds.length} contact${contactIds.length === 1 ? '' : 's'} · Do Not Contact entries are skipped`} size="sm"
      footer={<><button type="button" className="btn-ghost" onClick={onClose}>Cancel</button><button type="button" className="btn-primary" disabled={!ok || add.isPending} onClick={() => add.mutate(undefined)}><Megaphone size={14} />Add</button></>}>
      <div className="space-y-3">
        <select aria-label="Campaign" className="input" value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">Choose a campaign…</option>
          {campaigns.data?.filter((c) => c.status !== 'COMPLETED').map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          <option value="new">+ New campaign</option>
        </select>
        {choice === 'new' && <>
          <input aria-label="Campaign name" className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Johor Manufacturing — AI Productivity" maxLength={200} />
          <select aria-label="Programme" className="input" value={program} onChange={(e) => setProgram(e.target.value)}>
            <option value="">Programme (optional)</option>{meta?.programs.filter((p) => p.enabled).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </>}
      </div>
    </Modal>
  );
}
