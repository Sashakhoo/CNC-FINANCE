import clsx from 'clsx';
import { CheckCircle2, Info, AlertTriangle, XCircle, Search, Mail, UserCheck, Flag, CalendarCheck, MessageSquare, StickyNote, Activity as ActIcon, Megaphone, PenLine } from 'lucide-react';
import { useUi } from '../../store/useUi';
import type { Activity } from '../../types';
import { fmtDateTime, timeAgo } from '../../utils/format';

export function EmptyState({ title, body, actions, icon }: { title: string; body: string; actions?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-14 h-14 rounded-2xl bg-s2 border border-line flex items-center justify-center text-mute mb-5">{icon ?? <Search size={22} />}</div>
      <div className="eyebrow text-fg mb-2">{title}</div>
      <p className="text-sm text-mute max-w-sm">{body}</p>
      {actions && <div className="flex flex-wrap justify-center gap-2 mt-6">{actions}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} aria-hidden />;
}

const ACT_ICON: Record<string, React.ReactNode> = {
  discovered: <Search size={13} />, created: <Search size={13} />, drafted: <PenLine size={13} />, email: <Mail size={13} />,
  linkedin: <MessageSquare size={13} />, meeting: <CalendarCheck size={13} />, call: <UserCheck size={13} />, note: <StickyNote size={13} />,
  status: <Flag size={13} />, activity: <ActIcon size={13} />, updated: <PenLine size={13} />, campaign: <Megaphone size={13} />,
};

export function ActivityTimeline({ items }: { items: Activity[] }) {
  if (!items.length) return <p className="text-sm text-mute py-4">No activity yet.</p>;
  return (
    <ol className="relative">
      {items.map((a, i) => (
        <li key={a.id} className="relative flex gap-3.5 pb-5 last:pb-0">
          {i < items.length - 1 && <span className="absolute left-[15px] top-8 bottom-0 w-px bg-line" aria-hidden />}
          <span className={clsx('w-8 h-8 rounded-full border flex items-center justify-center shrink-0',
            ['meeting', 'call'].includes(a.type) || a.meta?.to === 'WON' ? 'bg-lime-soft border-lime/40 text-lime' : 'bg-s2 border-line text-mute')} aria-hidden>
            {ACT_ICON[a.type] ?? <ActIcon size={13} />}
          </span>
          <div className="min-w-0 pt-1">
            <div className="text-sm text-fg break-words">{a.text}</div>
            <div className="text-xs text-dim mt-0.5" title={fmtDateTime(a.created_at)}>
              {a.user ? `${a.user} · ` : ''}{timeAgo(a.created_at)}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function MatchRing({ value, size = 92 }: { value: number; size?: number }) {
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative inline-flex items-center justify-center shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${value}% match`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" className="stroke-line" strokeWidth={6} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" className="stroke-lime" strokeWidth={6} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} />
      </svg>
      <div className="absolute text-center">
        <div className="num text-xl font-medium leading-none">{value}%</div>
        <div className="text-[9px] tracking-[0.12em] text-mute mt-1">MATCH</div>
      </div>
    </div>
  );
}

export function Bar({ value, max = 100, tone = 'lime' }: { value: number; max?: number; tone?: 'lime' | 'amber' | 'mute' }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="h-1.5 w-full rounded-full bg-line overflow-hidden" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={clsx('h-full rounded-full transition-all duration-500', tone === 'lime' ? 'bg-lime' : tone === 'amber' ? 'bg-amber' : 'bg-mute')} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Toasts() {
  const toasts = useUi((s) => s.toasts);
  const drop = useUi((s) => s.dropToast);
  return (
    <div className="fixed bottom-5 right-5 z-[70] flex flex-col gap-2 w-[min(360px,calc(100vw-40px))]" aria-live="polite" role="status">
      {toasts.map((t) => (
        <div key={t.id} className="flex items-center gap-3 bg-s2 border border-line2 rounded-2xl pl-4 pr-2 py-3 shadow-2xl animate-fadein">
          <span className={clsx(t.tone === 'ok' && 'text-lime', t.tone === 'info' && 'text-sky', t.tone === 'warn' && 'text-amber', t.tone === 'error' && 'text-danger')} aria-hidden>
            {t.tone === 'ok' ? <CheckCircle2 size={17} /> : t.tone === 'info' ? <Info size={17} /> : t.tone === 'warn' ? <AlertTriangle size={17} /> : <XCircle size={17} />}
          </span>
          <span className="text-sm flex-1">{t.text}</span>
          <button type="button" className="w-7 h-7 rounded-full text-mute hover:text-fg hover:bg-white/5" onClick={() => drop(t.id)} aria-label="Dismiss notification">×</button>
        </div>
      ))}
    </div>
  );
}

export function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="relative group inline-flex">
      {children}
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 whitespace-nowrap rounded-lg bg-fg text-bg text-[11px] px-2 py-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity z-40">
        {text}
      </span>
    </span>
  );
}
