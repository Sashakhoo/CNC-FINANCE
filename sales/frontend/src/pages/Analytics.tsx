import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { ChartCard, MetricCard, PageHeader, Segmented } from '../components/common/Card';
import { C, GroupedBars, HatchBars, MultiLine, QualityDonut } from '../components/dashboard/Charts';
import { EmptyState, Skeleton } from '../components/common/Misc';
import { fmtNum, fmtRM } from '../utils/format';

interface Perf { name: string; prospects: number; reached: number; responded: number; meetings: number; won: number; response_rate: number | null; avg_lead_score: number | null }
interface Report {
  days: number;
  lead_growth: { week: string; leads: number; high: number; medium: number; companies: number }[];
  confidence_distribution: { range: string; contacts: number }[];
  qualified: Record<'HIGH' | 'MEDIUM' | 'LOW', number>;
  funnel: Record<string, number>;
  rates: { response: number | null; meeting: number | null; proposal: number | null; win: number | null };
  pipeline_value: number; revenue_won: number;
  industry: Perf[]; location: Perf[]; role: Perf[]; lead_source: Perf[];
  campaigns: { id: number; name: string; status: string; prospects: number; contacted: number; meeting: number; proposal: number; won: number; pipeline_value: number; won_value: number; response_rate: number | null }[];
  providers: { provider: string; calls: number; success_rate: number | null; avg_ms: number | null; companies_found: number; emails_found: number; verification_results: Record<string, number> }[];
  rates_basis: string;
}

const RANGES = ['90D', '180D', '365D'] as const;
const pct = (v: number | null) => (v === null ? '—' : `${v}%`);

function PerfTable({ title, rows, subtitle }: { title: string; rows: Perf[]; subtitle?: string }) {
  return (
    <ChartCard title={title} subtitle={subtitle}>
      {!rows.length ? <p className="text-sm text-mute py-4">No data yet.</p> : (
        <div className="overflow-x-auto"><table className="tbl w-full border-separate border-spacing-0">
          <thead><tr><th>Name</th><th>Prospects</th><th>Reached</th><th>Response</th><th>Meetings</th><th>Won</th><th>Avg lead</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.name}><td className="font-medium">{r.name}</td><td className="num">{r.prospects}</td><td className="num">{r.reached}</td>
              <td>{pct(r.response_rate)}</td><td className="num">{r.meetings}</td><td className="num">{r.won}</td><td>{r.avg_lead_score ?? '—'}</td></tr>))}</tbody>
        </table></div>
      )}
    </ChartCard>
  );
}

export default function Analytics() {
  const [range, setRange] = useState<(typeof RANGES)[number]>('180D');
  const days = parseInt(range, 10);
  const q = useQuery({ queryKey: ['analytics', 'report', days], queryFn: () => api<Report>(`/analytics/report?days=${days}`) });
  const demand = useQuery({ queryKey: ['analytics', 'summary', 30], queryFn: () => api<{ training_demand: { program: string; companies: number }[] }>('/analytics/summary?days=30') });
  if (q.isPending) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-72" /></div>;
  if (q.isError) return <p className="text-sm text-danger">{q.error.message}</p>;
  const r = q.data;
  const growth = r.lead_growth.map((w) => ({ label: new Date(w.week).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }), leads: w.leads, high: w.high, companies: w.companies }));
  return (
    <div className="space-y-6">
      <PageHeader title="Analytics" subtitle="Counted live from the database. Rates are based on each contact's current pipeline stage."
        actions={<Segmented label="Time range" value={range} options={RANGES} onChange={setRange} />} />
      {r.funnel.prospects === 0 && <EmptyState title="No data yet" body="Analytics fill in as Discovery finds prospects and you work the pipeline." actions={<Link to="/discovery" className="btn-ghost">Go to Discovery</Link>} />}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
        <MetricCard label="Prospects" value={fmtNum(r.funnel.prospects)} />
        <MetricCard label="Response rate" value={pct(r.rates.response)} />
        <MetricCard label="Meeting rate" value={pct(r.rates.meeting)} />
        <MetricCard label="Proposal rate" value={pct(r.rates.proposal)} />
        <MetricCard label="Win rate" value={pct(r.rates.win)} />
        <MetricCard label="Pipeline value" value={fmtRM(r.pipeline_value)} />
        <MetricCard label="Revenue won" value={fmtRM(r.revenue_won)} accent />
      </div>
      <div className="grid xl:grid-cols-[1.6fr_1fr] gap-4">
        <ChartCard title="Lead growth" subtitle={`New prospects and companies per week, last ${days} days`}>
          {growth.length ? <MultiLine data={growth} keys={[{ key: 'leads', name: 'Prospects', color: C.lime }, { key: 'high', name: 'High priority', color: C.fg }, { key: 'companies', name: 'Companies', color: C.mute, dash: true }]} />
            : <p className="text-sm text-mute py-10 text-center">No new prospects in this period.</p>}
        </ChartCard>
        <ChartCard title="Qualified leads" subtitle="Current lead-score priority">
          <QualityDonut data={(['HIGH', 'MEDIUM', 'LOW'] as const).map((k) => ({ name: k, value: r.qualified[k] }))} />
        </ChartCard>
      </div>
      <div className="grid xl:grid-cols-2 gap-4">
        <ChartCard title="Contact confidence" subtitle="How sure we are that contact details are correct">
          <HatchBars data={r.confidence_distribution.map((d) => ({ name: d.range, value: d.contacts }))} valueName="Contacts" />
        </ChartCard>
        <ChartCard title="Training demand" subtitle="Companies with a ≥60% training match">
          {demand.data?.training_demand.length ? <HatchBars data={demand.data.training_demand.map((d) => ({ name: d.program, value: d.companies }))} valueName="Companies" />
            : <p className="text-sm text-mute py-10 text-center">No training matches yet.</p>}
        </ChartCard>
      </div>
      {r.industry.length > 0 && <ChartCard title="Industry performance" subtitle="Prospects, reached and meetings by industry">
        <GroupedBars data={r.industry.map((i) => ({ label: i.name, prospects: i.prospects, reached: i.reached, meetings: i.meetings }))}
          keys={[{ key: 'prospects', name: 'Prospects', color: C.lime }, { key: 'reached', name: 'Reached', color: C.fg }, { key: 'meetings', name: 'Meetings', color: C.mute }]} />
      </ChartCard>}
      <div className="grid xl:grid-cols-2 gap-4">
        <PerfTable title="Location performance" rows={r.location} />
        <PerfTable title="Decision-maker role performance" rows={r.role} />
        <PerfTable title="Industry performance" rows={r.industry} />
        <PerfTable title="Lead-source performance" rows={r.lead_source} subtitle="Where each contact was first found" />
      </div>
      <ChartCard title="Campaign performance">
        {!r.campaigns.length ? <p className="text-sm text-mute py-4">No campaigns yet.</p> : (
          <div className="overflow-x-auto"><table className="tbl w-full border-separate border-spacing-0">
            <thead><tr><th>Campaign</th><th>Status</th><th>Prospects</th><th>Contacted</th><th>Meetings</th><th>Proposals</th><th>Won</th><th>Response</th><th>Pipeline</th><th>Won value</th></tr></thead>
            <tbody>{r.campaigns.map((c) => (
              <tr key={c.id}><td><Link to={`/campaigns/${c.id}`} className="hover:text-lime font-medium">{c.name}</Link></td><td className="text-xs">{c.status}</td>
                <td className="num">{c.prospects}</td><td className="num">{c.contacted}</td><td className="num">{c.meeting}</td><td className="num">{c.proposal}</td><td className="num">{c.won}</td>
                <td>{pct(c.response_rate)}</td><td>{fmtRM(c.pipeline_value)}</td><td>{fmtRM(c.won_value)}</td></tr>))}</tbody>
          </table></div>
        )}
      </ChartCard>
      <ChartCard title="Provider effectiveness" subtitle="Calls in this period and what each provider actually produced">
        {!r.providers.length ? <p className="text-sm text-mute py-4">No provider activity yet. <Link to="/providers" className="text-lime">Provider settings</Link></p> : (
          <div className="overflow-x-auto"><table className="tbl w-full border-separate border-spacing-0">
            <thead><tr><th>Provider</th><th>Calls</th><th>Success</th><th>Avg response</th><th>Companies found</th><th>Emails found</th><th>Verification results</th></tr></thead>
            <tbody>{r.providers.map((p) => (
              <tr key={p.provider}><td className="font-medium">{p.provider}</td><td className="num">{p.calls}</td><td>{pct(p.success_rate)}</td><td>{p.avg_ms === null ? '—' : `${p.avg_ms} ms`}</td>
                <td className="num">{p.companies_found}</td><td className="num">{p.emails_found}</td>
                <td className="text-xs">{Object.keys(p.verification_results).length ? Object.entries(p.verification_results).map(([k, v]) => `${k} ${v}`).join(' · ') : '—'}</td></tr>))}</tbody>
          </table></div>
        )}
      </ChartCard>
    </div>
  );
}
