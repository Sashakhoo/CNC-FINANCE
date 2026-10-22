import { useState } from 'react';
import clsx from 'clsx';
import { ArrowUpRight, CalendarClock, ChevronDown, Mail, Video } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../services/api';
import { useCrmMutation } from '../../hooks/useCrm';
import { useUi } from '../../store/useUi';
import { ContactAvatar, CompanyAvatar } from '../common/Avatar';
import { Modal } from '../common/Overlay';
import { shortName } from '../../utils/format';
import { STATUSES, statusLabel, type Prospect, type ProspectStatus } from '../../types';

/** Fixed next-step wording per pipeline stage (a label, not data). */
const NEXT: Record<ProspectStatus, string> = {
  NEW: 'Review Lead', REVIEW: 'Review Lead Fit', APPROVED: 'Send First Outreach', REJECTED: 'No Action — Rejected',
  CONTACTED: 'Follow Up on Outreach', REPLIED: 'Schedule Discovery Call', MEETING: 'Discovery Call', PROPOSAL: 'Chase Training Proposal',
  WON: 'Plan Training Delivery', LOST: 'Revisit Later', DO_NOT_CONTACT: 'Do Not Contact',
};

const dmy = (d: Date) => `${String(d.getDate()).padStart(2, '0')} ${String(d.getMonth() + 1).padStart(2, '0')} ${d.getFullYear()}`;
const hm = (d: Date) => d.toLocaleTimeString('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true }).replace(':00', '');

function ScheduleModal({ p, onClose }: { p: Prospect; onClose: () => void }) {
  const init = p.follow_up_at ? new Date(p.follow_up_at) : new Date(Date.now() + 2 * 86400000);
  const [date, setDate] = useState(init.toISOString().slice(0, 10));
  const [time, setTime] = useState(p.follow_up_at ? init.toTimeString().slice(0, 5) : '14:00');
  const save = useCrmMutation((iso: string | null) => api(`/contacts/${p.id}`, { method: 'PATCH', body: { follow_up_at: iso } }),
    { success: (r) => (r ? `Follow-up saved for ${p.full_name}` : null), onSuccess: onClose });
  return (
    <Modal open onClose={onClose} title="Schedule discovery call" subtitle={`${p.full_name} · ${p.company.display_name}`} size="sm"
      footer={<>
        {p.follow_up_at && <button type="button" className="btn-text mr-auto" onClick={() => save.mutate(null)}>Clear</button>}
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="button" className="btn-primary" disabled={!date || save.isPending} onClick={() => save.mutate(new Date(`${date}T${time || '09:00'}:00`).toISOString())}>Save</button>
      </>}>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5"><span className="label">Date</span><input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <label className="flex flex-col gap-1.5"><span className="label">Time</span><input type="time" className="input" value={time} onChange={(e) => setTime(e.target.value)} /></label>
      </div>
      <p className="text-xs text-dim mt-3">Saved as the contact's follow-up and logged in their activity. No calendar invite is sent.</p>
    </Modal>
  );
}

export function WorkspaceCard({ p, featured, canEdit }: { p: Prospect; featured?: boolean; canEdit?: boolean }) {
  const nav = useNavigate();
  const ask = useUi((s) => s.ask);
  const [scheduling, setScheduling] = useState(false);
  const status = useCrmMutation((s: ProspectStatus) => api(`/contacts/${p.id}/status`, { body: { status: s } }), { success: `${p.full_name} updated` });
  const follow = p.follow_up_at ? new Date(p.follow_up_at) : null;
  const ink = featured ? 'text-ink' : 'text-fg';
  const sub = featured ? 'text-ink/60' : 'text-mute';
  const ring = featured ? 'border-ink/25' : 'border-line2';
  const blocked = p.suppressed || p.status === 'DO_NOT_CONTACT';

  const change = (s: ProspectStatus) => {
    if (s === p.status) return;
    if (s === 'WON') { nav(`/contacts/${p.id}`); return; }
    if (s === 'DO_NOT_CONTACT') { ask({ title: 'Mark Do Not Contact?', message: `${p.full_name} and their emails go on the suppression list. Only an admin can undo this.`, confirmLabel: 'Do Not Contact', danger: true, onConfirm: () => status.mutate(s) }); return; }
    status.mutate(s);
  };

  return (
    <article className={clsx('relative rounded-[30px] p-3 flex flex-col min-h-[270px] transition-colors', featured ? 'bg-lime' : 'bg-s1 border border-line hover:border-line2')} aria-label={p.full_name}>
      {/* page-coloured notch in the top-right corner cradling the open button */}
      <span className="absolute -top-px -right-px w-[80px] h-[80px] bg-bg rounded-bl-[30px]" aria-hidden />
      <Link to={`/contacts/${p.id}`} className="absolute top-1 right-1 w-[70px] h-[70px] rounded-full border border-line2 bg-bg flex items-center justify-center text-fg hover:border-lime hover:text-lime transition-colors" aria-label={`Open ${p.full_name}`}>
        <ArrowUpRight size={20} />
      </Link>

      <div className="flex items-center gap-3 pr-[86px] min-h-[58px]">
        <ContactAvatar name={p.full_name} size={48} />
        <div className="min-w-0">
          <div className={clsx('font-display text-[21px] leading-tight tracking-tight truncate', ink)}>{p.full_name}</div>
          <div className={clsx('text-xs truncate', sub)}>{p.original_title ?? 'Title unknown'} at {shortName(p.company.display_name)}</div>
        </div>
      </div>

      <div className="flex items-center gap-3 mt-9">
        <span className={clsx('w-12 h-12 rounded-full border flex items-center justify-center shrink-0', ring, ink)} aria-hidden><CalendarClock size={18} /></span>
        <div className="min-w-0">
          <div className={clsx('font-display text-[20px] leading-tight tracking-tight', ink)}>{NEXT[p.status]}</div>
          <div className={clsx('text-[13px] mt-1 tabular-nums truncate', sub)}>
            {follow ? <>{dmy(follow)} · {hm(follow)}</> : 'No follow-up scheduled'}{p.training_program ? ` · ${p.training_program}` : ''}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1.5 mt-auto pt-6">
        <label className={clsx('relative flex-1 min-w-0 h-12 rounded-full border flex items-center gap-2 pl-1.5 pr-3', ring)}>
          <span className="sr-only">Pipeline status for {p.full_name}</span>
          <CompanyAvatar name={p.company.display_name} size={36} />
          <select value={p.status} disabled={!canEdit || status.isPending} onChange={(e) => change(e.target.value as ProspectStatus)}
            className={clsx('appearance-none bg-transparent flex-1 min-w-0 text-sm outline-none cursor-pointer disabled:cursor-default', ink)}>
            {STATUSES.map((s) => <option key={s} value={s} className="text-fg bg-s1">{statusLabel(s).charAt(0) + statusLabel(s).slice(1).toLowerCase()}</option>)}
          </select>
          <ChevronDown size={15} className={clsx('pointer-events-none', ink)} aria-hidden />
        </label>
        {p.email && !blocked
          ? <a href={`mailto:${encodeURIComponent(p.email)}`} className={clsx('w-12 h-12 rounded-full border flex items-center justify-center shrink-0 hover:bg-black/5', ring, ink)} aria-label={`Email ${p.full_name} from your mail app`} title={p.email}><Mail size={17} /></a>
          : <span className={clsx('w-12 h-12 rounded-full border flex items-center justify-center shrink-0 opacity-35', ring, ink)} title={blocked ? 'Do Not Contact' : 'No email on file'} aria-label={blocked ? 'Email blocked: Do Not Contact' : 'No email on file'}><Mail size={17} /></span>}
        <button type="button" disabled={!canEdit || blocked} onClick={() => setScheduling(true)}
          className={clsx('w-12 h-12 rounded-full flex items-center justify-center shrink-0 disabled:opacity-35', featured ? 'bg-ink text-lime' : 'bg-fg text-bg')} aria-label={`Schedule a call with ${p.full_name}`}><Video size={17} /></button>
      </div>
      {scheduling && <ScheduleModal p={p} onClose={() => setScheduling(false)} />}
    </article>
  );
}
