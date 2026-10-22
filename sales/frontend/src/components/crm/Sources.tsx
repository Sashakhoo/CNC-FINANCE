import { useState } from 'react';
import { ExternalLink, FileSearch } from 'lucide-react';
import { Drawer } from '../common/Overlay';
import { ProvenanceBadge } from '../common/Badges';
import { fmtDateTime } from '../../utils/format';
import type { Source } from '../../types';

const FIELD_LABEL: Record<string, string> = {
  legal_name: 'Company name', full_name: 'Name', title: 'Job title', website: 'Website', industry: 'Industry',
  employee_estimate: 'Employees', general_email: 'General email', phone: 'Phone', description: 'Description',
  address: 'Address', city: 'City', state: 'State', country: 'Country',
};

export function SafeLink({ href, children, className }: { href: string; children?: React.ReactNode; className?: string }) {
  const ok = /^https?:\/\//i.test(href);
  if (!ok) return <span className={className}>{children ?? href}</span>;
  return <a href={href} target="_blank" rel="noopener noreferrer nofollow" className={className ?? 'text-lime hover:underline break-all'}>{children ?? href}</a>;
}

export function SourceList({ sources }: { sources: Source[] }) {
  if (!sources.length) return <p className="text-sm text-mute">No sources recorded.</p>;
  return (
    <ul className="space-y-3">
      {sources.map((s) => (
        <li key={s.id} className="p-4 rounded-2xl bg-s2 border border-line">
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">{FIELD_LABEL[s.field] ?? s.field}</span>
            <ProvenanceBadge value={s.provenance} />
            <span className="text-[11px] text-dim">{s.source_type.replace(/_/g, ' ').toLowerCase()}{s.provider ? ` · ${s.provider}` : ''}</span>
            {s.confidence !== null && <span className="text-[11px] text-dim">· {Math.round(s.confidence * 100)}% confidence</span>}
          </div>
          {s.value && <div className="text-sm mt-2 break-words">{s.value}</div>}
          {s.evidence && <blockquote className="text-xs text-mute mt-2 pl-3 border-l-2 border-line2 italic">“{s.evidence}”</blockquote>}
          <div className="flex flex-wrap items-center gap-3 mt-2 text-[11px] text-dim">
            {s.source_url && <SafeLink href={s.source_url} className="inline-flex items-center gap-1 text-lime hover:underline break-all"><ExternalLink size={11} />{s.source_url}</SafeLink>}
            {s.retrieved_at && <span>Retrieved {fmtDateTime(s.retrieved_at)}</span>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SourcesButton({ sources, title }: { sources: Source[]; title: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn-ghost h-9" onClick={() => setOpen(true)}><FileSearch size={15} />View sources ({sources.length})</button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Sources" subtitle={title}>
        <p className="text-xs text-mute mb-4">Where each piece of information came from, how it was obtained, and when.</p>
        <SourceList sources={sources} />
      </Drawer>
    </>
  );
}
