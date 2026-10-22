import clsx from 'clsx';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export interface MenuItem {
  label: string;
  icon?: React.ReactNode;
  onSelect?: () => void;
  danger?: boolean;
  divider?: boolean;
  disabled?: boolean;
  submenu?: MenuItem[];
}

/** Dropdown rendered in a portal (so tables with overflow never clip it), keyboard navigable. */
export function Menu({ trigger, items, align = 'right', label }: { trigger: (p: { onClick: () => void; 'aria-expanded': boolean; 'aria-haspopup': 'menu' }) => React.ReactNode; items: MenuItem[]; align?: 'left' | 'right'; label: string }) {
  const [open, setOpen] = useState(false);
  const [sub, setSub] = useState<MenuItem[] | null>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const anchor = useRef<HTMLSpanElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !anchor.current) return;
    const r = anchor.current.getBoundingClientRect();
    const w = 230;
    const h = menu.current?.offsetHeight ?? 300;
    let top = r.bottom + 6;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
    const left = align === 'right' ? Math.max(8, r.right - w) : Math.min(r.left, window.innerWidth - w - 8);
    setPos({ top, left });
  }, [open, sub, align]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node)) { setOpen(false); setSub(null); }
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); setSub(null); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const els = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
        const i = els.indexOf(document.activeElement as HTMLButtonElement);
        els[(i + (e.key === 'ArrowDown' ? 1 : -1) + els.length) % els.length]?.focus();
      }
    };
    const scroll = () => { setOpen(false); setSub(null); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', key);
    window.addEventListener('resize', scroll);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', key); window.removeEventListener('resize', scroll); };
  }, [open]);

  useEffect(() => { if (open) menu.current?.querySelector<HTMLButtonElement>('button')?.focus(); }, [open, sub]);

  const list = sub ?? items;
  return (
    <>
      <span ref={anchor} className="inline-flex">{trigger({ onClick: () => { setOpen((o) => !o); setSub(null); }, 'aria-expanded': open, 'aria-haspopup': 'menu' })}</span>
      {open && createPortal(
        <div ref={menu} role="menu" aria-label={label} className="fixed z-[60] w-[230px] max-h-[70vh] overflow-y-auto rounded-2xl bg-s2 border border-line2 shadow-2xl p-1.5 animate-fadein" style={pos}>
          {sub && (
            <button type="button" role="menuitem" className="w-full text-left px-3 py-2 text-xs text-mute hover:text-fg rounded-lg" onClick={() => setSub(null)}>← Back</button>
          )}
          {list.map((it, i) => it.divider ? <div key={i} className="h-px bg-line my-1.5" /> : (
            <button key={i} type="button" role="menuitem" disabled={it.disabled}
              className={clsx('w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left transition-colors disabled:opacity-40', it.danger ? 'text-danger hover:bg-danger-soft' : 'text-fg hover:bg-s3')}
              onClick={(e) => {
                e.stopPropagation();
                if (it.submenu) { setSub(it.submenu); return; }
                setOpen(false); setSub(null); it.onSelect?.();
              }}>
              {it.icon && <span className="text-mute w-4 inline-flex" aria-hidden>{it.icon}</span>}
              <span className="flex-1">{it.label}</span>
              {it.submenu && <span className="text-dim" aria-hidden>›</span>}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
