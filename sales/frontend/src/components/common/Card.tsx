import clsx from 'clsx';
import { ArrowUpRight, TrendingDown, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
        <h1 className="h-display text-3xl sm:text-[40px] leading-[1.05]">{title}</h1>
        {subtitle && <p className="text-mute mt-2 text-sm sm:text-[15px]">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function MetricCard({ label, value, change, hint, to, accent }: { label: string; value: React.ReactNode; change?: number; hint?: string; to?: string; accent?: boolean }) {
  const up = (change ?? 0) >= 0;
  const body = (
    <div className={clsx('card card-pad h-full flex flex-col gap-4 group transition-colors', accent ? 'bg-lime text-ink border-lime' : 'hover:border-line2')}>
      <div className="flex items-start justify-between gap-2">
        <span className={clsx('text-[13px] truncate', accent ? 'text-ink/70' : 'text-mute')}>{label}</span>
        {to && <ArrowUpRight size={16} className={clsx('transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5', accent ? '' : 'text-dim')} aria-hidden />}
      </div>
      <div className="num text-[21px] sm:text-[26px] 2xl:text-[30px] leading-none font-medium whitespace-nowrap">{value}</div>
      {change !== undefined && (
        <div className={clsx('flex items-center gap-1.5 text-[11.5px] whitespace-nowrap mt-auto', accent ? 'text-ink/75' : up ? 'text-lime' : 'text-danger')}>
          {up ? <TrendingUp size={13} aria-hidden /> : <TrendingDown size={13} aria-hidden />}
          <span>{up ? '+' : ''}{change.toFixed(1)}%</span>
          <span className={clsx('truncate', accent ? 'text-ink/60' : 'text-dim')}>{hint ?? 'this month'}</span>
        </div>
      )}
    </div>
  );
  return to ? <Link to={to} className="block rounded-xl3">{body}</Link> : body;
}

export function ChartCard({ title, subtitle, actions, children, className }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={clsx('card card-pad flex flex-col min-w-0', className)} aria-label={title}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h2 className="font-display text-lg font-medium tracking-tight">{title}</h2>
          {subtitle && <div className="text-xs text-mute mt-1">{subtitle}</div>}
        </div>
        {actions && <div className="flex items-center gap-1.5 shrink-0">{actions}</div>}
      </div>
      <div className="flex-1 min-h-0">{children}</div>
    </section>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: readonly T[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex p-1 rounded-full bg-s2 border border-line">
      {options.map((o) => (
        <button key={o} type="button" role="radio" aria-checked={o === value} onClick={() => onChange(o)}
          className={clsx('h-7 px-3 rounded-full text-xs font-medium transition-colors', o === value ? 'bg-fg text-bg' : 'text-mute hover:text-fg')}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="label mb-1">{label}</div>
      <div className="text-sm text-fg break-words">{children}</div>
    </div>
  );
}
