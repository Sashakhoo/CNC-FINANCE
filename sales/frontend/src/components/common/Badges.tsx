import clsx from 'clsx';
import type { EmailStatus, Priority, Provenance, ProspectStatus } from '../../types';
import { statusLabel } from '../../types';

const STATUS_STYLE: Record<ProspectStatus, string> = {
  NEW: 'text-fg border-line2 bg-s2',
  REVIEW: 'text-amber border-amber/30 bg-amber-soft',
  APPROVED: 'text-lime border-lime/30 bg-lime-soft',
  REJECTED: 'text-dim border-line bg-transparent',
  CONTACTED: 'text-sky border-sky/30 bg-sky-soft',
  REPLIED: 'text-sky border-sky/40 bg-sky-soft',
  MEETING: 'text-ink border-lime bg-lime',
  PROPOSAL: 'text-fg border-lime/50 bg-lime-soft',
  WON: 'text-ink border-lime-pale bg-lime-pale',
  LOST: 'text-dim border-line bg-transparent line-through',
  DO_NOT_CONTACT: 'text-danger border-danger/30 bg-danger-soft',
};

const STATUS_DOT: Partial<Record<ProspectStatus, string>> = { NEW: 'bg-fg', REVIEW: 'bg-amber', APPROVED: 'bg-lime', CONTACTED: 'bg-sky', REPLIED: 'bg-sky' };

export function StatusBadge({ status }: { status: ProspectStatus }) {
  return (
    <span className={clsx('inline-flex items-center gap-1.5 h-6 px-2.5 rounded-full border text-[10.5px] font-semibold tracking-[0.06em] whitespace-nowrap', STATUS_STYLE[status])}>
      {STATUS_DOT[status] && <span className={clsx('w-1.5 h-1.5 rounded-full', STATUS_DOT[status])} aria-hidden />}
      {statusLabel(status)}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  const cls = priority === 'HIGH' ? 'text-lime' : priority === 'MEDIUM' ? 'text-amber' : 'text-dim';
  const bars = priority === 'HIGH' ? 3 : priority === 'MEDIUM' ? 2 : 1;
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-[10.5px] font-semibold tracking-[0.08em]', cls)}>
      <span className="flex items-end gap-[2px] h-3" aria-hidden>
        {[1, 2, 3].map((b) => (
          <span key={b} className={clsx('w-[3px] rounded-sm', b <= bars ? 'bg-current' : 'bg-line2')} style={{ height: `${b * 4}px` }} />
        ))}
      </span>
      {priority}
    </span>
  );
}

export function ScoreBadge({ score, size = 'md', label = 'Lead score' }: { score: number; size?: 'sm' | 'md' | 'lg'; label?: string }) {
  const tone = score >= 80 ? 'lime' : score >= 60 ? 'amber' : 'dim';
  const dim = size === 'lg' ? 64 : size === 'md' ? 38 : 30;
  const r = dim / 2 - 3;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative inline-flex items-center justify-center shrink-0" style={{ width: dim, height: dim }} title={`${label} ${score} / 100`}>
      <svg width={dim} height={dim} className="-rotate-90" aria-hidden>
        <circle cx={dim / 2} cy={dim / 2} r={r} fill="none" className="stroke-line" strokeWidth={size === 'lg' ? 4 : 2.5} />
        <circle cx={dim / 2} cy={dim / 2} r={r} fill="none" className={tone === 'lime' ? 'stroke-lime' : tone === 'amber' ? 'stroke-amber' : 'stroke-dim'} strokeWidth={size === 'lg' ? 4 : 2.5} strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} strokeLinecap="round" />
      </svg>
      <span className={clsx('absolute num font-medium', size === 'lg' ? 'text-xl' : size === 'md' ? 'text-[13px]' : 'text-[11px]', tone === 'lime' ? 'text-lime' : tone === 'amber' ? 'text-amber' : 'text-mute')}>
        {score}
      </span>
    </span>
  );
}

/** Score or an explicit "not calculated" — never a placeholder number. */
export function MaybeScore({ value, suffix = '', title }: { value: number | null | undefined; suffix?: string; title: string }) {
  if (value === null || value === undefined) return <span className="text-xs text-dim" title={`${title}: not calculated yet`}>—</span>;
  const tone = value >= 80 ? 'text-lime' : value >= 60 ? 'text-amber' : 'text-mute';
  return <span className={clsx('num text-sm', tone)} title={title}>{value}{suffix}</span>;
}

const EMAIL_STYLE: Record<EmailStatus, { cls: string; icon: string }> = {
  VERIFIED: { cls: 'text-lime', icon: '✓' },
  LIKELY: { cls: 'text-amber', icon: '~' },
  UNVERIFIED: { cls: 'text-mute', icon: '?' },
  INVALID: { cls: 'text-danger', icon: '×' },
  RISKY: { cls: 'text-amber', icon: '!' },
  UNKNOWN: { cls: 'text-dim', icon: '–' },
};

export function EmailBadge({ status }: { status: EmailStatus }) {
  const s = EMAIL_STYLE[status];
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-[10.5px] font-semibold tracking-[0.06em]', s.cls)}>
      <span className="w-4 h-4 rounded-full border border-current/40 inline-flex items-center justify-center text-[10px] leading-none" aria-hidden>{s.icon}</span>
      {status}
    </span>
  );
}

const PROV_STYLE: Record<Provenance, string> = {
  DISCOVERED: 'text-sky border-sky/30', INFERRED: 'text-amber border-amber/40', ENRICHED: 'text-fg border-line2',
  VERIFIED: 'text-lime border-lime/40', USER_PROVIDED: 'text-mute border-line2',
};

export function ProvenanceBadge({ value }: { value: Provenance }) {
  return <span className={clsx('inline-flex items-center h-5 px-2 rounded-full border text-[9.5px] font-semibold tracking-[0.08em] whitespace-nowrap', PROV_STYLE[value])}>{value.replace('_', ' ')}</span>;
}

export function Chip({ children, onRemove, active }: { children: React.ReactNode; onRemove?: () => void; active?: boolean }) {
  return (
    <span className={clsx('inline-flex items-center gap-1.5 h-7 pl-3 rounded-full text-xs border', onRemove ? 'pr-1.5' : 'pr-3', active ? 'bg-lime-soft border-lime/40 text-lime' : 'bg-s2 border-line text-fg')}>
      {children}
      {onRemove && (
        <button type="button" onClick={onRemove} className="w-5 h-5 rounded-full hover:bg-white/10 inline-flex items-center justify-center" aria-label="Remove filter">×</button>
      )}
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex items-center h-7 px-3 rounded-full bg-s2 border border-line text-xs text-mute">{children}</span>;
}
