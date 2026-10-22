import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { useMe } from '../hooks/useAuth';
import { ChartCard, MetricCard, Segmented } from '../components/common/Card';
import { Funnel, HatchBars, LeadAreaChart, QualityDonut } from '../components/dashboard/Charts';
import { EmptyState, Skeleton } from '../components/common/Misc';
import { fmtDateTime, fmtNum, fmtRM, greeting } from '../utils/format';
import type { ProspectStatus } from '../types';

interface Summary {
  companies: number; prospects: number; high_priority: number; verified_emails: number;
  meetings: number; proposals: number; won: number; pipeline_value: number; won_value: number;
  funnel: { stage: ProspectStatus; count: number }[];
  quality: { name: string; value: number }[];
  acquisition: { date: string; leads: number }[];
  training_demand: { program: string; companies: number }[];
  recent_jobs: { id: number; name: string; job_type: string; status: string; progress: number; created_at: string }[];
  demo_mode: boolean;
}

const RANGES = ['7D', '30D', '90D'] as const;

/** Fill missing days with 0 so the chart's x-axis is continuous. */
function dailySeries(points: Summary['acquisition'], days: number) {
  const byDay = new Map(points.map((p) => [p.date, p.leads]));
  const out: { label: string; leads: number; high: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    out.push({ label: d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }), leads: byDay.get(key) ?? 0, high: 0 });
  }
  return out;
}

export default function Dashboard() {
  const me = useMe().data;
  const [range, setRange] = useState<(typeof RANGES)[number]>('30D');
  const days = parseInt(range, 10);
  const q = useQuery({ queryKey: ['analytics', 'summary', days], queryFn: () => api<Summary>(`/analytics/summary?days=${days}`) });
  const m = q.data;
  const series = useMemo(() => (m ? dailySeries(m.acquisition, days) : []), [m, days]);

  return (
    <div className="space-y-6">
      <div>
        <div className="eyebrow mb-2">Corporate training pipeline{m?.demo_mode ? ' · DEMO MODE' : ''}</div>
        <h1 className="h-display text-4xl sm:text-[52px] leading-[1]">{greeting()}{me ? `, ${me.username}` : ''}.</h1>
        <p className="text-mute mt-3">Every number here is counted live from the database.</p>
      </div>

      {q.isError && <div role="alert" className="card card-pad text-danger text-sm">Couldn't load the dashboard: {q.error.message}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        {!m ? Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[120px]" />) : <>
          <MetricCard label="Companies" value={fmtNum(m.companies)} />
          <MetricCard label="Prospects" value={fmtNum(m.prospects)} />
          <MetricCard label="High Priority Leads" value={fmtNum(m.high_priority)} />
          <MetricCard label="Verified Emails" value={fmtNum(m.verified_emails)} />
          <MetricCard label="Meetings" value={fmtNum(m.meetings)} />
          <MetricCard label="Proposals" value={fmtNum(m.proposals)} />
          <MetricCard label="Won Clients" value={fmtNum(m.won)} />
          <MetricCard label="Pipeline Value" value={fmtRM(m.pipeline_value)} accent />
        </>}
      </div>

      {m && m.prospects === 0 && m.companies === 0 && (
        <EmptyState title="No prospects yet" body="Companies and decision makers appear here once discovery runs or leads are imported. Discovery and import arrive in the next phases." />
      )}

      {m && (
        <>
          <div className="grid xl:grid-cols-[1.6fr_1fr] gap-4">
            <ChartCard title="Lead Acquisition" subtitle={<><span className="num text-fg text-base">{fmtNum(series.reduce((s, x) => s + x.leads, 0))}</span> new prospects in the last {days} days</>}
              actions={<Segmented label="Time range" value={range} options={RANGES} onChange={setRange} />}>
              <LeadAreaChart data={series} />
            </ChartCard>
            <ChartCard title="Lead Quality" subtitle="Prospects by lead-score priority">
              <div className="h-full flex items-center"><QualityDonut data={m.quality} /></div>
            </ChartCard>
          </div>
          <div className="grid xl:grid-cols-2 gap-4">
            <ChartCard title="Training Demand" subtitle="Companies with a ≥60% match, by programme">
              {m.training_demand.length
                ? <HatchBars data={m.training_demand.map((d) => ({ name: d.program, value: d.companies }))} valueName="Companies" />
                : <p className="text-sm text-mute py-10 text-center">No training matches calculated yet.</p>}
            </ChartCard>
            <ChartCard title="Pipeline" subtitle={<>Stage counts · <span className="text-fg">{fmtRM(m.won_value)}</span> invoiced from won deals</>}>
              <Funnel data={m.funnel} />
            </ChartCard>
          </div>
          <ChartCard title="Recent Discovery Jobs" subtitle="Latest background jobs">
            {m.recent_jobs.length ? (
              <ul className="divide-y divide-line">
                {m.recent_jobs.map((j) => (
                  <li key={j.id} className="py-3 flex items-center justify-between gap-4 text-sm">
                    <span className="truncate">{j.name}</span>
                    <span className="text-mute text-xs whitespace-nowrap">{j.status} · {Math.round(j.progress)}% · {fmtDateTime(j.created_at)}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-mute py-6 text-center">No jobs have run yet. <Link to="/jobs" className="text-lime">Jobs</Link></p>}
          </ChartCard>
        </>
      )}
    </div>
  );
}
