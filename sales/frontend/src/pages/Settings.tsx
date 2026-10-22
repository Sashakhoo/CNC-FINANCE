import { useState } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useMe } from '../hooks/useAuth';
import { qs, useCrmMutation } from '../hooks/useCrm';
import { useUi } from '../store/useUi';
import { ChartCard, PageHeader } from '../components/common/Card';
import { Switch } from '../components/common/Form';
import { fmtDateTime } from '../utils/format';
import type { Paged } from '../types';

const TABS = ['General', 'Team & roles', 'Training programmes', 'Do Not Contact', 'Duplicates', 'Retention', 'Scoring'] as const;
type SettingsMap = Record<string, { value: Record<string, unknown>; version: number; updated_at: string }>;

const general = z.object({
  company_name: z.string().trim().min(1, 'Required').max(200), sender_name: z.string().trim().max(120),
  sender_title: z.string().trim().max(120), currency: z.string().trim().min(1).max(8),
});

function General({ settings, admin }: { settings: SettingsMap; admin: boolean }) {
  const v = settings.general?.value as z.infer<typeof general> | undefined;
  const { register, handleSubmit, formState: { errors, isDirty } } = useForm<z.infer<typeof general>>({ resolver: zodResolver(general), values: v });
  const save = useCrmMutation((b: z.infer<typeof general>) => api('/settings/general', { method: 'PUT', body: b }), { success: 'Settings saved' });
  return (
    <ChartCard title="General" subtitle="Used in outreach drafts and documents.">
      <form onSubmit={handleSubmit((b) => save.mutate(b))} className="grid sm:grid-cols-2 gap-4 max-w-2xl" noValidate>
        {(['company_name', 'sender_name', 'sender_title', 'currency'] as const).map((k) => (
          <label key={k} className="flex flex-col gap-1.5"><span className="label">{k.replace('_', ' ')}</span>
            <input className="input" disabled={!admin} {...register(k)} />{errors[k] && <span className="text-xs text-danger">{errors[k]?.message}</span>}</label>
        ))}
        {admin && <div className="sm:col-span-2"><button type="submit" className="btn-primary" disabled={!isDirty || save.isPending}>Save</button></div>}
      </form>
      {!admin && <p className="text-xs text-dim mt-3">Only admins can change settings.</p>}
    </ChartCard>
  );
}

function Team() {
  const me = useMe().data;
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<{ id: number; username: string; role: string; finance_role: string; last_login_at: string | null }[]>('/auth/users') });
  const setRole = useCrmMutation((b: { id: number; role: string }) => api(`/auth/users/${b.id}`, { method: 'PATCH', body: { role: b.role } }), { success: 'Role updated', onSuccess: () => users.refetch() });
  return (
    <ChartCard title="Team & roles" subtitle="Accounts and passwords live in Finance (Team screen). Roles here control what each person can do in Sales.">
      {users.isError ? <p className="text-sm text-danger">{users.error.message}</p> : (
        <table className="tbl w-full border-separate border-spacing-0">
          <thead><tr><th>User</th><th>Finance role</th><th>Sales role</th></tr></thead>
          <tbody>{(users.data ?? []).map((u) => (
            <tr key={u.id}><td>{u.username}{u.id === me?.id && <span className="text-xs text-dim"> (you)</span>}</td><td className="text-mute">{u.finance_role}</td>
              <td><select aria-label={`Role for ${u.username}`} className="h-9 rounded-full bg-s2 border border-line px-3 text-sm" value={u.role} disabled={u.id === me?.id}
                onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}>
                {['ADMIN', 'SALES', 'VIEWER'].map((r) => <option key={r}>{r}</option>)}</select></td></tr>))}</tbody>
        </table>
      )}
      <p className="text-xs text-dim mt-3">ADMIN: everything including settings and the audit log · SALES: work leads and the pipeline · VIEWER: read-only. People appear here after their first sign-in.</p>
    </ChartCard>
  );
}

function Programmes({ admin }: { admin: boolean }) {
  const programs = useQuery({ queryKey: ['programs'], queryFn: () => api<{ id: number; name: string; description: string; enabled: boolean; keywords: string[] }[]>('/programs') });
  const toggle = useCrmMutation((b: { id: number; enabled: boolean }) => api(`/programs/${b.id}`, { method: 'PATCH', body: { enabled: b.enabled } }), { success: 'Programme updated', onSuccess: () => programs.refetch() });
  return (
    <ChartCard title="Training programmes" subtitle="Programmes the training-match engine can recommend. Keywords are matched against evidence from company websites.">
      <ul className="divide-y divide-line">{(programs.data ?? []).map((p) => (
        <li key={p.id} className="py-3 flex items-start gap-4">
          <Switch checked={p.enabled} onChange={(v) => admin && toggle.mutate({ id: p.id, enabled: v })} label={`${p.enabled ? 'Disable' : 'Enable'} ${p.name}`} />
          <div className="min-w-0"><div className="text-sm font-medium">{p.name}</div><p className="text-xs text-mute">{p.description}</p>
            <p className="text-[11px] text-dim mt-1">Keywords: {p.keywords.join(', ')}</p></div>
        </li>))}</ul>
    </ChartCard>
  );
}

function DoNotContact({ admin }: { admin: boolean }) {
  const [page, setPage] = useState(1);
  const [form, setForm] = useState({ kind: 'EMAIL', value: '', reason: '' });
  const ask = useUi((s) => s.ask);
  const canEdit = useMe().data?.can_edit;
  const list = useQuery({ queryKey: ['suppression', page], queryFn: () => api<Paged<{ id: number; kind: string; value: string; reason: string; user: string | null; created_at: string }>>(`/suppression${qs({ page, page_size: 50 })}`) });
  const add = useCrmMutation(() => api('/suppression', { body: form }), { success: 'Added to Do Not Contact', onSuccess: () => setForm({ ...form, value: '', reason: '' }) });
  const remove = useCrmMutation((id: number) => api(`/suppression/${id}`, { method: 'DELETE' }), { success: 'Removed' });
  return (
    <ChartCard title="Do Not Contact" subtitle="Anyone matching an entry here is excluded from outreach and exports.">
      {canEdit && <form className="flex flex-wrap gap-2 mb-4" onSubmit={(e) => { e.preventDefault(); add.mutate(undefined); }}>
        <select aria-label="Type" className="h-10 rounded-full bg-s2 border border-line px-3 text-sm" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="EMAIL">Email</option><option value="DOMAIN">Domain</option></select>
        <input aria-label="Email or domain" className="input w-64" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} placeholder={form.kind === 'EMAIL' ? 'name@company.com' : 'company.com'} />
        <input aria-label="Reason" className="input w-64" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Reason (optional)" maxLength={500} />
        <button type="submit" className="btn-ghost" disabled={form.value.trim().length < 3 || add.isPending}>Add</button>
      </form>}
      <table className="tbl w-full border-separate border-spacing-0">
        <thead><tr><th>Type</th><th>Value</th><th>Reason</th><th>Added</th><th /></tr></thead>
        <tbody>{(list.data?.items ?? []).map((s) => (
          <tr key={s.id}><td className="text-xs">{s.kind}</td><td className="break-all whitespace-normal">{s.value}</td><td className="text-mute whitespace-normal">{s.reason}</td><td className="text-xs text-dim">{s.user ?? '—'} · {fmtDateTime(s.created_at)}</td>
            <td>{admin && s.kind !== 'CONTACT' && <button type="button" className="icon-btn-sm" aria-label={`Remove ${s.value}`} onClick={() => ask({ title: 'Remove from Do Not Contact?', message: `${s.value} could be selected for outreach again.`, confirmLabel: 'Remove', danger: true, onConfirm: () => remove.mutate(s.id) })}><Trash2 size={13} /></button>}</td></tr>))}</tbody>
      </table>
      {!list.data?.items.length && <p className="text-sm text-mute py-4">The list is empty.</p>}
      {(list.data?.total ?? 0) > 50 && <div className="flex gap-2 mt-3"><button type="button" className="btn-ghost h-8" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button type="button" className="btn-ghost h-8" disabled={page * 50 >= (list.data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next</button></div>}
      <p className="text-xs text-dim mt-3">Contacts marked Do Not Contact appear here automatically; lift that from the contact's page (admin only).</p>
    </ChartCard>
  );
}

function Scoring({ settings }: { settings: SettingsMap }) {
  const lead = settings.lead_scoring?.value ?? {};
  const conf = settings.contact_confidence?.value ?? {};
  const row = (k: string, v: unknown) => <tr key={k}><td className="text-mute">{k.replace(/_/g, ' ')}</td><td className="whitespace-normal">{typeof v === 'object' ? Object.entries(v as Record<string, unknown>).map(([a, b]) => `${a}: ${b}`).join(' · ') : String(v)}</td></tr>;
  return (
    <div className="space-y-4">
      <ChartCard title="Lead score weights" subtitle="How valuable a prospect is. Read-only here for now.">
        <table className="tbl w-full border-separate border-spacing-0"><tbody>{Object.entries(lead).map(([k, v]) => row(k, v))}</tbody></table>
      </ChartCard>
      <ChartCard title="Contact confidence weights" subtitle="How sure we are that contact details are correct. Read-only here for now.">
        <table className="tbl w-full border-separate border-spacing-0"><tbody>{Object.entries(conf).map(([k, v]) => row(k, v))}</tbody></table>
      </ChartCard>
    </div>
  );
}

type DupSide = { id: number; name: string; detail: string; contacts?: number; emails?: string[]; status?: string; created_at: string };
type Dup = { id: number; entity_type: 'company' | 'contact'; similarity: number; reasons: string[]; left: DupSide; right: DupSide };

function Duplicates() {
  const canEdit = useMe().data?.can_edit;
  const q = useQuery({ queryKey: ['duplicates'], queryFn: () => api<Dup[]>('/duplicates') });
  const merge = useCrmMutation((b: { id: number; keep: 'left' | 'right' }) => api(`/duplicates/${b.id}/merge`, { body: { keep: b.keep } }),
    { success: 'Records merged', onSuccess: () => q.refetch() });
  const dismiss = useCrmMutation((id: number) => api(`/duplicates/${id}/dismiss`, { body: {} }), { success: 'Marked as not a duplicate', onSuccess: () => q.refetch() });
  const side = (d: Dup, s: DupSide, which: 'left' | 'right') => (
    <div className="flex-1 min-w-[220px] p-4 rounded-2xl bg-s2 border border-line">
      <Link to={`/${d.entity_type === 'company' ? 'companies' : 'contacts'}/${s.id}`} className="font-medium hover:text-lime">{s.name}</Link>
      <div className="text-xs text-mute mt-1">{s.detail}</div>
      {s.emails && <div className="text-xs text-dim mt-1">{s.emails.join(', ') || 'No email'}</div>}
      {s.contacts !== undefined && <div className="text-xs text-dim mt-1">{s.contacts} contacts</div>}
      {canEdit && <button type="button" className="btn-ghost h-8 mt-3 text-xs" onClick={() => merge.mutate({ id: d.id, keep: which })}>Keep this one</button>}
    </div>
  );
  return (
    <ChartCard title="Possible duplicates" subtitle="Flagged by discovery, import and manual entry. Nothing is merged unless you choose — the kept record gains the other's emails, sources, notes and activity.">
      {!q.data?.length ? <p className="text-sm text-mute py-4">No open duplicates.</p> : (
        <ul className="space-y-4">{q.data.map((d) => (
          <li key={d.id} className="border-b border-line pb-4 last:border-0">
            <div className="text-xs text-mute mb-2">{d.entity_type} · {Math.round(d.similarity * 100)}% similar · {d.reasons.join('; ')}</div>
            <div className="flex flex-wrap gap-3 items-stretch">{side(d, d.left, 'left')}{side(d, d.right, 'right')}</div>
            {canEdit && <button type="button" className="btn-text h-8 mt-2 text-xs" onClick={() => dismiss.mutate(d.id)}>Not a duplicate</button>}
          </li>))}</ul>
      )}
    </ChartCard>
  );
}

const retentionSchema = z.object({
  activity_days: z.coerce.number().int().min(30).max(3650), crawl_page_days: z.coerce.number().int().min(30).max(3650),
  rejected_contact_days: z.coerce.number().int().min(30).max(3650),
});

function Retention({ settings, admin }: { settings: SettingsMap; admin: boolean }) {
  const ask = useUi((s) => s.ask);
  const v = settings.retention?.value as z.infer<typeof retentionSchema> | undefined;
  const { register, handleSubmit, formState: { errors, isDirty } } = useForm<z.infer<typeof retentionSchema>>({ resolver: zodResolver(retentionSchema), values: v });
  const save = useCrmMutation((b: z.infer<typeof retentionSchema>) => api('/settings/retention', { method: 'PUT', body: b }), { success: 'Retention saved', onSuccess: () => preview.refetch() });
  const preview = useQuery({ queryKey: ['retention'], enabled: admin, queryFn: () => api<{ crawl_pages: number; activities: number; rejected_contacts: number }>('/retention/preview') });
  const run = useCrmMutation(() => api<{ crawl_pages: number; activities: number; rejected_contacts: number }>('/retention/run', { body: {} }),
    { success: (r) => `Removed ${r.crawl_pages} pages, ${r.activities} activities, ${r.rejected_contacts} rejected contacts`, onSuccess: () => preview.refetch() });
  const LABEL = { crawl_page_days: 'Crawled page text (days)', activity_days: 'Activity history (days)', rejected_contact_days: 'Rejected contacts (days after rejection)' } as Record<string, string>;
  return (
    <ChartCard title="Data retention" subtitle="Old data is removed automatically every night at 03:45. Do Not Contact entries are never removed.">
      <form onSubmit={handleSubmit((b) => save.mutate(b))} className="grid sm:grid-cols-3 gap-4 max-w-3xl" noValidate>
        {(['crawl_page_days', 'activity_days', 'rejected_contact_days'] as const).map((k) => (
          <label key={k} className="flex flex-col gap-1.5"><span className="label">{LABEL[k]}</span>
            <input className="input" inputMode="numeric" disabled={!admin} {...register(k)} />{errors[k] && <span className="text-xs text-danger">30–3650 days</span>}</label>
        ))}
        {admin && <div className="sm:col-span-3"><button type="submit" className="btn-primary" disabled={!isDirty || save.isPending}>Save</button></div>}
      </form>
      {admin && preview.data && (
        <div className="mt-6 p-4 rounded-2xl bg-s2 border border-line flex flex-wrap items-center gap-4 text-sm">
          <span>Due for removal now: <span className="num">{preview.data.crawl_pages}</span> pages · <span className="num">{preview.data.activities}</span> activities · <span className="num">{preview.data.rejected_contacts}</span> rejected contacts</span>
          <button type="button" className="btn-danger h-9 ml-auto" disabled={run.isPending || !(preview.data.crawl_pages + preview.data.activities + preview.data.rejected_contacts)}
            onClick={() => ask({ title: 'Run retention now?', message: 'This permanently removes the data listed. It also runs automatically every night.', confirmLabel: 'Run now', danger: true, onConfirm: () => run.mutate(undefined) })}>Run now</button>
        </div>
      )}
    </ChartCard>
  );
}

export default function Settings() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState<(typeof TABS)[number]>((TABS as readonly string[]).includes(params.get('tab') ?? '') ? params.get('tab') as (typeof TABS)[number] : 'General');
  const admin = useMe().data?.role === 'ADMIN';
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<SettingsMap>('/settings') });
  const tabs = TABS.filter((t) => t !== 'Team & roles' || admin);
  return (
    <div>
      <PageHeader title="Settings" subtitle="Workspace configuration. Every change is recorded in the audit log." />
      <div className="grid lg:grid-cols-[220px_1fr] gap-6 items-start">
        <div role="tablist" aria-label="Settings sections" aria-orientation="vertical" className="flex lg:flex-col gap-1 overflow-x-auto lg:sticky lg:top-[96px]">
          {tabs.map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={clsx('h-10 px-4 rounded-full text-sm text-left whitespace-nowrap', tab === t ? 'bg-fg text-bg' : 'text-mute hover:text-fg hover:bg-s2')}>{t}</button>
          ))}
        </div>
        <div className="min-w-0" role="tabpanel" aria-label={tab}>
          {settings.isError && <p className="text-sm text-danger">{settings.error.message}</p>}
          {settings.data && tab === 'General' && <General settings={settings.data} admin={admin} />}
          {tab === 'Team & roles' && admin && <Team />}
          {tab === 'Training programmes' && <Programmes admin={admin} />}
          {tab === 'Do Not Contact' && <DoNotContact admin={admin} />}
          {tab === 'Duplicates' && <Duplicates />}
          {settings.data && tab === 'Retention' && <Retention settings={settings.data} admin={admin} />}
          {settings.data && tab === 'Scoring' && <Scoring settings={settings.data} />}
        </div>
      </div>
    </div>
  );
}
