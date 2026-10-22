import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate } from 'react-router-dom';
import { Modal } from '../common/Overlay';
import { api } from '../../services/api';
import { useCrmMutation, useMeta } from '../../hooks/useCrm';
import { useUi } from '../../store/useUi';
import type { CompanyDetail, ContactDetail } from '../../types';

const opt = (max: number) => z.string().trim().max(max).optional().or(z.literal(''));
const url = z.string().trim().max(1000).optional().or(z.literal(''))
  .refine((v) => !v || /^(https?:\/\/)?[^\s/]+\.[^\s]+$/i.test(v), 'Enter a web address like example.com');
const clean = <T extends Record<string, unknown>>(v: T) =>
  Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x === '' ? null : x])) as T;

function FieldRow({ label, error, children, hint }: { label: string; error?: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="label">{label}</span>
      {children}
      {error ? <span className="text-xs text-danger">{error}</span> : hint ? <span className="text-xs text-dim">{hint}</span> : null}
    </label>
  );
}

const companySchema = z.object({
  legal_name: z.string().trim().min(2, 'Enter the company name').max(300),
  website: url, industry: opt(120), description: opt(5000),
  // '' first: z.coerce.number() would turn a blank field into 0.
  employee_estimate: z.union([z.literal(''), z.coerce.number().int().min(1).max(10_000_000)]).optional(),
  phone: opt(60), general_email: z.string().trim().email('Not a valid email').optional().or(z.literal('')),
  deal_value: z.union([z.literal(''), z.coerce.number().min(0).max(100_000_000)]).optional(),
  address: opt(1000), city: opt(120), state: opt(120), country: opt(80), source_url: url,
});
type CompanyForm = z.infer<typeof companySchema>;

export function CompanyFormModal({ open, onClose, company }: { open: boolean; onClose: () => void; company?: CompanyDetail }) {
  const nav = useNavigate();
  const meta = useMeta().data;
  const [dupes, setDupes] = useState<{ id: number; legal_name: string; similarity: number }[]>([]);
  const loc = company?.location;
  const { register, handleSubmit, formState: { errors }, reset } = useForm<CompanyForm>({
    resolver: zodResolver(companySchema),
    values: company ? {
      legal_name: company.legal_name, website: company.website ?? '', industry: company.industry ?? '', description: company.description ?? '',
      employee_estimate: company.employee_estimate ?? '', phone: company.phone ?? '', general_email: company.general_email ?? '',
      deal_value: company.deal_value ?? '', address: loc?.address ?? '', city: loc?.city ?? '', state: loc?.state ?? '', country: loc?.country ?? '', source_url: '',
    } : undefined,
  });
  const save = useCrmMutation(
    (v: CompanyForm) => company
      ? api<CompanyDetail>(`/companies/${company.id}`, { method: 'PATCH', body: clean(v) })
      : api<CompanyDetail>('/companies', { body: clean(v) }),
    {
      success: company ? 'Company updated' : 'Company added',
      onSuccess: (r) => {
        const d = (r as CompanyDetail & { possible_duplicates?: typeof dupes }).possible_duplicates ?? [];
        if (!company && d.length) { setDupes(d); return; }
        reset(); onClose();
        if (!company) nav(`/companies/${r.id}`);
      },
    });

  return (
    <Modal open={open} onClose={() => { setDupes([]); onClose(); }} size="lg" title={company ? 'Edit company' : 'Add company'}
      subtitle="Everything you enter is stored as USER PROVIDED, with the source link if you give one."
      footer={dupes.length ? <button type="button" className="btn-primary" onClick={() => { setDupes([]); onClose(); }}>Done</button> : <>
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" form="company-form" className="btn-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
      </>}>
      {dupes.length ? (
        <div className="space-y-3">
          <p className="text-sm">Saved. These existing companies have similar names — they have been flagged for review, not merged:</p>
          <ul className="space-y-2">{dupes.map((d) => (
            <li key={d.id}><button type="button" className="text-lime hover:underline text-sm" onClick={() => { onClose(); nav(`/companies/${d.id}`); }}>{d.legal_name}</button> <span className="text-xs text-dim">{Math.round(d.similarity * 100)}% similar</span></li>
          ))}</ul>
        </div>
      ) : (
        <form id="company-form" onSubmit={handleSubmit((v) => save.mutate(v))} className="grid sm:grid-cols-2 gap-4" noValidate>
          <div className="sm:col-span-2"><FieldRow label="Legal name *" error={errors.legal_name?.message}><input className="input" {...register('legal_name')} placeholder="e.g. Southern Precision Automation Sdn Bhd" /></FieldRow></div>
          <FieldRow label="Website" error={errors.website?.message}><input className="input" {...register('website')} placeholder="example.com.my" /></FieldRow>
          <FieldRow label="Industry" error={errors.industry?.message}>
            <input className="input" list="industries" {...register('industry')} />
            <datalist id="industries">{meta?.industries.map((i) => <option key={i} value={i} />)}</datalist>
          </FieldRow>
          <FieldRow label="Employees" error={errors.employee_estimate?.message}><input className="input" inputMode="numeric" {...register('employee_estimate')} /></FieldRow>
          <FieldRow label="Deal value (RM)" error={errors.deal_value?.message} hint="Needed before a deal can be marked WON"><input className="input" inputMode="decimal" {...register('deal_value')} /></FieldRow>
          <FieldRow label="Phone" error={errors.phone?.message}><input className="input" {...register('phone')} /></FieldRow>
          <FieldRow label="General email" error={errors.general_email?.message}><input className="input" type="email" {...register('general_email')} /></FieldRow>
          <div className="sm:col-span-2"><FieldRow label="Address" error={errors.address?.message}><input className="input" {...register('address')} /></FieldRow></div>
          <FieldRow label="City" error={errors.city?.message}><input className="input" {...register('city')} /></FieldRow>
          <FieldRow label="State" error={errors.state?.message}>
            <input className="input" list="states" {...register('state')} />
            <datalist id="states">{meta?.states.map((s) => <option key={s} value={s} />)}</datalist>
          </FieldRow>
          <div className="sm:col-span-2"><FieldRow label="Description" error={errors.description?.message}><textarea className="input h-24 py-2" {...register('description')} /></FieldRow></div>
          <div className="sm:col-span-2"><FieldRow label="Where did this information come from?" error={errors.source_url?.message} hint="Optional link (company website page, directory listing…) saved as the source"><input className="input" {...register('source_url')} placeholder="https://" /></FieldRow></div>
        </form>
      )}
    </Modal>
  );
}

const contactSchema = z.object({
  full_name: z.string().trim().min(2, 'Enter the person’s name').max(200),
  original_title: opt(200), phone: opt(60),
  email: z.string().trim().email('Not a valid email').optional().or(z.literal('')),
  profile_url: url, source_url: url,
});
type ContactForm = z.infer<typeof contactSchema>;

export function ContactFormModal({ open, onClose, companyId, companyName }: { open: boolean; onClose: () => void; companyId: number; companyName: string }) {
  const nav = useNavigate();
  const toast = useUi((s) => s.toast);
  const { register, handleSubmit, formState: { errors }, reset } = useForm<ContactForm>({ resolver: zodResolver(contactSchema) });
  const save = useCrmMutation((v: ContactForm) => api<ContactDetail>('/contacts', { body: { ...clean(v), company_id: companyId } }), {
    success: 'Contact added to Review',
    onSuccess: (r) => {
      if (r.possible_duplicates?.length) toast(`Possible duplicate of ${r.possible_duplicates.map((d) => d.full_name).join(', ')} — check before outreach`, 'warn');
      reset(); onClose(); nav(`/contacts/${r.id}`);
    },
  });
  return (
    <Modal open={open} onClose={onClose} title="Add decision maker" subtitle={`At ${companyName}. New contacts start in REVIEW.`}
      footer={<>
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" form="contact-form" className="btn-primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Add contact'}</button>
      </>}>
      <form id="contact-form" onSubmit={handleSubmit((v) => save.mutate(v))} className="grid sm:grid-cols-2 gap-4" noValidate>
        <FieldRow label="Full name *" error={errors.full_name?.message}><input className="input" {...register('full_name')} /></FieldRow>
        <FieldRow label="Job title" error={errors.original_title?.message} hint="Normalized automatically (department, seniority)"><input className="input" {...register('original_title')} /></FieldRow>
        <FieldRow label="Business email" error={errors.email?.message} hint="Saved as UNVERIFIED"><input className="input" type="email" {...register('email')} /></FieldRow>
        <FieldRow label="Phone" error={errors.phone?.message}><input className="input" {...register('phone')} /></FieldRow>
        <div className="sm:col-span-2"><FieldRow label="Professional profile URL" error={errors.profile_url?.message}><input className="input" {...register('profile_url')} placeholder="https://www.linkedin.com/in/…" /></FieldRow></div>
        <div className="sm:col-span-2"><FieldRow label="Source of this information" error={errors.source_url?.message} hint="e.g. the company's management page"><input className="input" {...register('source_url')} placeholder="https://" /></FieldRow></div>
      </form>
    </Modal>
  );
}

export function NotesPanel({ notes, target, canEdit }: { notes: { id: number; body: string; user: string | null; created_at: string }[]; target: { contact_id?: number; company_id?: number }; canEdit: boolean }) {
  const [body, setBody] = useState('');
  const add = useCrmMutation(() => api('/notes', { body: { ...target, body } }), { success: 'Note saved', onSuccess: () => setBody('') });
  const del = useCrmMutation((id: number) => api(`/notes/${id}`, { method: 'DELETE' }), { success: 'Note deleted' });
  return (
    <div className="space-y-4">
      {canEdit && (
        <form onSubmit={(e) => { e.preventDefault(); if (body.trim()) add.mutate(undefined); }} className="space-y-2">
          <textarea aria-label="New note" className="input h-20 py-2" value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add a note…" maxLength={10000} />
          <div className="flex justify-end"><button type="submit" className="btn-ghost h-9" disabled={!body.trim() || add.isPending}>Save note</button></div>
        </form>
      )}
      {!notes.length && <p className="text-sm text-mute">No notes yet.</p>}
      <ul className="space-y-3">
        {notes.map((n) => (
          <li key={n.id} className="p-4 rounded-2xl bg-s2 border border-line">
            <p className="text-sm whitespace-pre-wrap break-words">{n.body}</p>
            <div className="flex items-center justify-between mt-2 text-[11px] text-dim">
              <span>{n.user ?? '—'} · {new Date(n.created_at).toLocaleString('en-GB')}</span>
              {canEdit && <button type="button" className="hover:text-danger" onClick={() => del.mutate(n.id)}>Delete</button>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const ACTIVITY_TYPES = [['call', 'Call'], ['meeting', 'Meeting'], ['email', 'Email sent'], ['linkedin', 'LinkedIn message'], ['other', 'Other']] as const;

export function LogActivity({ target }: { target: { contact_id?: number; company_id?: number } }) {
  const [type, setType] = useState<string>('call');
  const [text, setText] = useState('');
  const log = useCrmMutation(() => api('/activities', { body: { ...target, activity_type: type, text } }), { success: 'Activity logged', onSuccess: () => setText('') });
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) log.mutate(undefined); }} className="flex flex-wrap gap-2 mb-5">
      <select aria-label="Activity type" className="h-10 rounded-full bg-s2 border border-line px-3 text-sm" value={type} onChange={(e) => setType(e.target.value)}>
        {ACTIVITY_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <input aria-label="What happened" className="input flex-1 min-w-[180px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="What happened?" maxLength={2000} />
      <button type="submit" className="btn-ghost" disabled={!text.trim() || log.isPending}>Log</button>
    </form>
  );
}
