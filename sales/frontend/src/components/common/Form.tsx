import clsx from 'clsx';
import { Search } from 'lucide-react';

export function Field({ label, htmlFor, children, hint, className }: { label: string; htmlFor?: string; children: React.ReactNode; hint?: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      <label htmlFor={htmlFor} className="label">{label}</label>
      {children}
      {hint && <div className="text-xs text-dim">{hint}</div>}
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder, className, id, autoFocus }: { value: string; onChange: (v: string) => void; placeholder: string; className?: string; id?: string; autoFocus?: boolean }) {
  return (
    <div className={clsx('relative', className)}>
      <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-dim pointer-events-none" aria-hidden />
      <input id={id} type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        autoFocus={autoFocus} className="input pl-10 rounded-full" />
    </div>
  );
}

export function Select({ value, onChange, options, label, className, placeholder }: { value: string; onChange: (v: string) => void; options: (string | { value: string; label: string })[]; label: string; className?: string; placeholder?: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
      className={clsx('h-9 max-w-[170px] rounded-full bg-s2 border px-3 pr-8 text-xs outline-none transition-colors cursor-pointer', value ? 'border-lime/50 text-lime' : 'border-line text-mute hover:text-fg', className)}>
      <option value="">{placeholder ?? label}</option>
      {options.map((o) => typeof o === 'string' ? <option key={o} value={o}>{o}</option> : <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function ToggleChips({ options, value, onChange, label }: { options: string[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button key={o} type="button" aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={clsx('h-8 px-3.5 rounded-full text-xs border transition-colors', on ? 'bg-lime-soft border-lime/50 text-lime' : 'bg-s2 border-line text-mute hover:text-fg hover:border-line2')}>
            {on && <span aria-hidden>✓ </span>}{o}
          </button>
        );
      })}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={clsx('relative w-10 h-6 rounded-full transition-colors shrink-0', checked ? 'bg-lime' : 'bg-line2')}>
      <span className={clsx('absolute top-1 w-4 h-4 rounded-full transition-all', checked ? 'left-5 bg-ink' : 'left-1 bg-mute')} />
    </button>
  );
}
