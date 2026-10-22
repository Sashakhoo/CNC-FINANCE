import { useState } from 'react';
import clsx from 'clsx';
import { PlugZap } from 'lucide-react';
import { api } from '../services/api';
import { useMe } from '../hooks/useAuth';
import { useProviders } from '../hooks/useJobs';
import { useUi } from '../store/useUi';
import { ChartCard, PageHeader } from '../components/common/Card';
import { Skeleton } from '../components/common/Misc';
import { fmtDateTime } from '../utils/format';

const KIND_LABEL: Record<string, string> = { SEARCH: 'Search provider', EMAIL_DISCOVERY: 'Email discovery', EMAIL_VERIFICATION: 'Email verification', AI: 'LLM' };
const ENV: Record<string, string> = { SEARCH: 'SEARCH_PROVIDER + SEARCH_API_KEY', EMAIL_DISCOVERY: 'EMAIL_DISCOVERY_PROVIDER + EMAIL_DISCOVERY_API_KEY', EMAIL_VERIFICATION: 'EMAIL_VERIFICATION_PROVIDER + EMAIL_VERIFICATION_API_KEY', AI: 'LLM_PROVIDER + the matching *_API_KEY' };

function StatePill({ state }: { state: string }) {
  return <span className={clsx('inline-flex h-6 px-2.5 items-center rounded-full border text-[10.5px] font-semibold tracking-[0.06em]',
    state === 'CONNECTED' ? 'bg-lime text-ink border-lime' : state === 'CONFIGURED' ? 'text-fg border-line2' : state === 'ERROR' ? 'text-danger border-danger/30 bg-danger-soft' : 'text-mute border-line')}>{state.replace('_', ' ')}</span>;
}

export default function Providers() {
  const q = useProviders();
  const admin = useMe().data?.role === 'ADMIN';
  const toast = useUi((s) => s.toast);
  const [tested, setTested] = useState<Record<string, { state: string; message: string; http_status: number | null }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const test = async (kind: string) => {
    setBusy(kind);
    try {
      const r = await api<{ state: string; message: string; http_status: number | null }>(`/providers/${kind}/test`, { body: {} });
      setTested((t) => ({ ...t, [kind]: r }));
    } catch (e) { toast((e as Error).message, 'error'); } finally { setBusy(null); }
  };
  if (q.isPending) return <Skeleton className="h-80" />;
  if (q.isError) return <p className="text-danger text-sm">{q.error.message}</p>;
  const kinds = ['SEARCH', 'EMAIL_DISCOVERY', 'EMAIL_VERIFICATION', 'AI'];
  return (
    <div className="space-y-6">
      <PageHeader title="Provider Usage" subtitle="Which external providers are connected, and how much each has been used. Keys are never shown." />
      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
        {kinds.map((k) => {
          const rows = q.data.providers.filter((p) => p.kind === k);
          const chosen = rows.find((p) => p.state === 'CONFIGURED');
          const t = tested[k];
          return (
            <section key={k} className="card card-pad flex flex-col gap-3">
              <div className="eyebrow">{KIND_LABEL[k]}</div>
              <div className="flex items-center justify-between gap-2"><span className="font-display text-xl">{chosen?.display_name ?? 'None'}</span><StatePill state={t?.state ?? (chosen ? 'CONFIGURED' : 'NOT_CONFIGURED')} /></div>
              {t && <p className="text-xs text-mute">{t.message || '—'}{t.http_status ? ` (HTTP ${t.http_status})` : ''}</p>}
              <p className="text-[11px] text-dim">Available: {rows.map((r) => r.display_name).join(', ')}. Set {ENV[k]}.</p>
              {admin && <button type="button" className="btn-ghost h-9 mt-auto" disabled={busy === k} onClick={() => test(k)}><PlugZap size={14} />{busy === k ? 'Testing…' : 'Test connection'}</button>}
            </section>
          );
        })}
      </div>
      <ChartCard title="Usage" subtitle="Counted from every recorded provider call. Cost appears only where the provider publishes a per-request price.">
        {!q.data.usage.length ? <p className="text-sm text-mute py-4">No provider calls yet.</p> : (
          <div className="overflow-x-auto"><table className="tbl w-full border-separate border-spacing-0">
            <thead><tr><th>Provider</th><th>Today</th><th>This month</th><th>Success</th><th>Errors</th><th>Avg response</th><th>Est. cost</th><th>Last used</th></tr></thead>
            <tbody>{q.data.usage.map((u) => (
              <tr key={u.provider}><td><div className="font-medium">{u.provider}</div><div className="text-[11px] text-dim">{KIND_LABEL[u.kind] ?? u.kind}</div>
                {u.recent_errors.length > 0 && <div className="text-[11px] text-danger whitespace-normal mt-1">Recent: {u.recent_errors.map((e) => `${e.error_type ?? 'error'}${e.http_status ? ` ${e.http_status}` : ''}`).join(', ')}</div>}</td>
                <td className="num">{u.requests_today}</td><td className="num">{u.requests_month}</td>
                <td>{u.success_rate === null ? '—' : `${u.success_rate}%`}</td><td className={u.errors_month ? 'text-danger' : ''}>{u.errors_month}</td>
                <td>{u.avg_ms === null ? '—' : `${u.avg_ms} ms`}</td><td>{u.estimated_cost === null ? 'Not available' : `$${u.estimated_cost.toFixed(2)}`}</td>
                <td className="text-xs">{u.last_used ? fmtDateTime(u.last_used) : '—'}</td></tr>))}</tbody>
          </table></div>
        )}
      </ChartCard>
    </div>
  );
}
