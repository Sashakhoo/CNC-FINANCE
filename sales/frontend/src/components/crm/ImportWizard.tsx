import { useState } from 'react';
import clsx from 'clsx';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { FileUp, Upload } from 'lucide-react';
import { apiForm } from '../../services/api';
import { useUi } from '../../store/useUi';
import { Modal } from '../common/Overlay';

interface Preview { filename: string; headers: string[]; rows: string[][]; total: number; mapping: Record<string, string | null>; fields: string[] }
interface Result { job_id: number; companies_created: number; companies_updated: number; contacts_created: number; contacts_updated: number; emails_added: number; duplicates_flagged: number; skipped: number; skipped_rows: { row: number; reason: string }[] }

const LABELS: Record<string, string> = {
  company: 'Company name', website: 'Website', domain: 'Domain', contact: 'Full name', first_name: 'First name', last_name: 'Last name',
  title: 'Job title', email: 'Business email', phone: 'Phone', profile: 'Professional profile URL', city: 'City', state: 'State',
  industry: 'Industry', employees: 'Company size', source: 'Source',
};
const STEPS = ['Upload', 'Map columns', 'Preview', 'Import'];

export function ImportWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useUi((s) => s.toast);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const reset = () => { setFile(null); setPreview(null); setMapping({}); setStep(0); setError(''); setResult(null); };
  const close = () => { reset(); onClose(); };

  const upload = async (f: File) => {
    setFile(f); setBusy(true); setError('');
    const form = new FormData(); form.append('file', f);
    try {
      const p = await apiForm<Preview>('/import/preview', form);
      setPreview(p); setMapping(p.mapping); setStep(1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const commit = async () => {
    if (!file) return;
    setBusy(true); setError('');
    const form = new FormData(); form.append('file', file); form.append('mapping', JSON.stringify(mapping));
    try {
      const r = await apiForm<Result>('/import/commit', form);
      setResult(r); setStep(3);
      ['companies', 'prospects', 'analytics', 'jobs'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(`Imported ${r.contacts_created} contact${r.contacts_created === 1 ? '' : 's'}, ${r.companies_created} compan${r.companies_created === 1 ? 'y' : 'ies'}`);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const col = (field: string) => (preview && mapping[field] ? preview.headers.indexOf(mapping[field]!) : -1);
  const valid = !!(mapping.company || mapping.website || mapping.domain);

  return (
    <Modal open={open} onClose={close} size="xl" title="Import leads" subtitle="CSV or XLSX, up to 5,000 rows. Existing values are never overwritten; Do Not Contact entries are skipped."
      footer={<>
        {step > 0 && step < 3 && <button type="button" className="btn-ghost mr-auto" onClick={() => setStep(step - 1)}>Back</button>}
        <button type="button" className="btn-ghost" onClick={close}>{step === 3 ? 'Close' : 'Cancel'}</button>
        {step === 1 && <button type="button" className="btn-primary" disabled={!valid} onClick={() => setStep(2)}>Preview</button>}
        {step === 2 && <button type="button" className="btn-primary" disabled={busy || !valid} onClick={commit}><Upload size={14} />{busy ? 'Importing…' : `Import ${preview?.total ?? 0} rows`}</button>}
      </>}>
      <ol className="flex gap-2 mb-5" aria-label="Import steps">
        {STEPS.map((s, i) => <li key={s} className={clsx('h-8 px-3 rounded-full text-xs inline-flex items-center border', i === step ? 'bg-fg text-bg border-fg' : i < step ? 'bg-lime text-ink border-lime' : 'border-line text-mute')}>{i + 1}. {s}</li>)}
      </ol>
      {error && <p role="alert" className="text-sm text-danger mb-3">{error}</p>}
      {step === 0 && (
        <label className="flex flex-col items-center justify-center gap-3 h-48 rounded-2xl border-2 border-dashed border-line2 bg-s2 cursor-pointer hover:border-lime">
          <FileUp size={28} className="text-mute" />
          <span className="text-sm">{busy ? 'Reading file…' : 'Choose a .csv or .xlsx file'}</span>
          <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
      )}
      {step === 1 && preview && (
        <div>
          <p className="text-sm text-mute mb-4">{preview.filename} · {preview.total} rows. Match your columns to fields (suggested automatically).</p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {preview.fields.map((f) => (
              <label key={f} className="flex flex-col gap-1.5"><span className="label">{LABELS[f] ?? f}</span>
                <select className="input" value={mapping[f] ?? ''} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value || null })}>
                  <option value="">— not in file —</option>{preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select></label>
            ))}
          </div>
          {!valid && <p className="text-xs text-amber mt-3">Map at least a company name or website column.</p>}
        </div>
      )}
      {step === 2 && preview && (
        <div className="overflow-x-auto">
          <p className="text-sm text-mute mb-3">First {Math.min(preview.rows.length, 10)} of {preview.total} rows, as they'll be imported:</p>
          <table className="tbl w-full border-separate border-spacing-0">
            <thead><tr>{['company', 'website', 'contact', 'title', 'email', 'state'].map((f) => <th key={f}>{LABELS[f]}</th>)}</tr></thead>
            <tbody>{preview.rows.slice(0, 10).map((r, i) => (
              <tr key={i}>{['company', 'website', 'contact', 'title', 'email', 'state'].map((f) => {
                const idx = col(f); let v = idx >= 0 ? r[idx] : '';
                if (f === 'contact' && !v) v = [r[col('first_name')] ?? '', r[col('last_name')] ?? ''].filter(Boolean).join(' ');
                return <td key={f} className="text-xs max-w-[220px] truncate">{v || <span className="text-dim">—</span>}</td>;
              })}</tr>))}</tbody>
          </table>
        </div>
      )}
      {step === 3 && result && (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {([['Companies created', result.companies_created], ['Companies updated', result.companies_updated], ['Contacts created', result.contacts_created],
              ['Contacts updated', result.contacts_updated], ['Emails added', result.emails_added], ['Possible duplicates', result.duplicates_flagged], ['Rows skipped', result.skipped]] as const).map(([l, v]) => (
              <div key={l} className="p-3 rounded-2xl bg-s2 border border-line"><dt className="text-[11px] text-mute">{l}</dt><dd className="num text-xl">{v}</dd></div>))}
          </dl>
          {result.skipped_rows.length > 0 && <div><div className="label mb-1">Skipped rows</div>
            <ul className="max-h-48 overflow-y-auto text-xs space-y-1">{result.skipped_rows.map((s, i) => <li key={i}>Row {s.row}: {s.reason}</li>)}</ul></div>}
          <div className="flex gap-2"><Link to="/prospects?status=REVIEW" className="btn-primary" onClick={close}>Review imported prospects</Link>
            {result.duplicates_flagged > 0 && <Link to="/settings?tab=Duplicates" className="btn-ghost" onClick={close}>Review duplicates</Link>}</div>
        </div>
      )}
    </Modal>
  );
}
