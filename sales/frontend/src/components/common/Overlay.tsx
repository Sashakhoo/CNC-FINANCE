import clsx from 'clsx';
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onClose]);
}

function useFocusFirst(open: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current?.querySelector<HTMLElement>('[data-autofocus], input, textarea, select, button:not([data-close])');
    el?.focus();
    return () => prev?.focus?.();
  }, [open]);
  return ref;
}

export function Modal({ open, onClose, title, subtitle, children, footer, size = 'md' }: {
  open: boolean; onClose: () => void; title: string; subtitle?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; size?: 'sm' | 'md' | 'lg' | 'xl';
}) {
  useEscape(open, onClose);
  const ref = useFocusFirst(open);
  if (!open) return null;
  const w = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-5xl' }[size];
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={clsx('relative w-full bg-s1 border border-line rounded-t-xl3 sm:rounded-xl3 shadow-2xl animate-fadein flex flex-col max-h-[92vh]', w)}>
        <div className="flex items-start justify-between gap-4 p-5 sm:p-6 pb-4">
          <div>
            <h2 className="font-display text-xl font-medium tracking-tight">{title}</h2>
            {subtitle && <div className="text-sm text-mute mt-1">{subtitle}</div>}
          </div>
          <button type="button" data-close className="icon-btn-sm" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="px-5 sm:px-6 pb-5 overflow-y-auto">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-5 sm:px-6 py-4 border-t border-line">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 'max-w-2xl' }: {
  open: boolean; onClose: () => void; title: string; subtitle?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; width?: string;
}) {
  useEscape(open, onClose);
  const ref = useFocusFirst(open);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={clsx('relative h-full w-full bg-s1 border-l border-line flex flex-col animate-slidein', width)}>
        <div className="flex items-start justify-between gap-4 p-6 border-b border-line">
          <div className="min-w-0">
            <h2 className="font-display text-xl font-medium tracking-tight">{title}</h2>
            {subtitle && <div className="text-sm text-mute mt-1">{subtitle}</div>}
          </div>
          <button type="button" data-close className="icon-btn-sm" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-6 py-4 border-t border-line">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger, onConfirm, onClose }: {
  open: boolean; title: string; message: React.ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<>
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="button" data-autofocus className={danger ? 'btn-danger' : 'btn-primary'} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</button>
      </>}>
      <p className="text-sm text-mute leading-relaxed">{message}</p>
    </Modal>
  );
}
