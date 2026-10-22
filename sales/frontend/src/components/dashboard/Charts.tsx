import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Line, LineChart, Legend } from 'recharts';
import { useNavigate } from 'react-router-dom';
import type { ProspectStatus } from '../../types';
import { fmtNum } from '../../utils/format';

const DARK = { lime: '#D3F25A', limeHi: '#E0F878', pale: '#E8F8AA', amber: '#E0A93B', mute: '#8C938A', dim: '#646b62', line: '#242824', s3: '#2a2f2a', sky: '#7FB2E5', fg: '#F4F5F2' };
const LIGHT = { lime: '#C6E83C', limeHi: '#D3F25A', pale: '#1E1E1E', amber: '#C98A10', mute: '#6C6C6A', dim: '#929290', line: '#DDDDDB', s3: '#E1E1DF', sky: '#2F6DAE', fg: '#1E1E1E' };
/** Chart palette; swapped in place when the theme changes (the app remounts on theme change). */
export const C = { ...DARK };
export const applyChartTheme = (t: 'dark' | 'light') => Object.assign(C, t === 'light' ? LIGHT : DARK);
const axis = { stroke: C.dim, fontSize: 11, tickLine: false, axisLine: false } as const;

export function ChartTooltip({ active, payload, label, suffix = '' }: { active?: boolean; payload?: { name: string; value: number; color?: string; payload?: { fill?: string } }[]; label?: string; suffix?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl bg-fg text-bg px-3 py-2 text-xs shadow-xl">
      {label && <div className="font-medium mb-1">{label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.color ?? p.payload?.fill }} />
          <span className="text-bg/70">{p.name}</span><span className="font-medium ml-auto pl-3 tabular-nums">{fmtNum(p.value)}{suffix}</span>
        </div>
      ))}
    </div>
  );
}

export const HatchDefs = ({ id = 'hatch' }: { id?: string }) => (
  <defs>
    <pattern id={id} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="7" height="7" fill="rgba(211,242,90,0.18)" />
      <line x1="0" y1="0" x2="0" y2="7" stroke={C.lime} strokeWidth="3.2" />
    </pattern>
    <linearGradient id={`${id}-fade`} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor={C.lime} stopOpacity={0.28} />
      <stop offset="100%" stopColor={C.lime} stopOpacity={0} />
    </linearGradient>
  </defs>
);

export function LeadAreaChart({ data, height = 260 }: { data: { label: string; leads: number; high: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 6, left: -18, bottom: 0 }}>
        <HatchDefs id="la" />
        <CartesianGrid stroke={C.line} strokeDasharray="2 6" vertical={false} />
        <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={18} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: C.line, strokeWidth: 1 }} />
        <Area type="monotone" dataKey="leads" name="New leads" stroke={C.lime} strokeWidth={2} fill="url(#la-fade)" dot={false} activeDot={{ r: 4, fill: C.lime, stroke: '#070807', strokeWidth: 2 }} />
        <Area type="monotone" dataKey="high" name="High priority" stroke={C.pale} strokeWidth={1.5} strokeDasharray="4 4" fill="transparent" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function QualityDonut({ data, height = 220 }: { data: { name: string; value: number }[]; height?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const fills = [C.lime, C.amber, C.s3];
  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <div className="relative" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="70%" outerRadius="100%" paddingAngle={3} cornerRadius={8} stroke="none" startAngle={90} endAngle={-270}>
              {data.map((d, i) => <Cell key={d.name} fill={fills[i]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="num text-3xl">{Math.round((data[0].value / total) * 100)}%</div>
          <div className="text-[10px] tracking-[0.14em] text-mute">HIGH QUALITY</div>
        </div>
      </div>
      <ul className="space-y-3 w-full sm:w-auto">
        {data.map((d, i) => (
          <li key={d.name} className="flex items-center gap-3 text-sm">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: fills[i] }} aria-hidden />
            <span className="w-20 text-mute">{d.name[0] + d.name.slice(1).toLowerCase()}</span>
            <span className="num w-10 text-right">{Math.round((d.value / total) * 100)}%</span>
            <span className="text-xs text-dim tabular-nums">{fmtNum(d.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Bar chart where the top value is drawn hatched (reference style), others muted. */
export function HatchBars({ data, height = 260, valueName = 'Prospects', onBarClick, layout = 'vertical' }: { data: { name: string; value: number }[]; height?: number; valueName?: string; onBarClick?: (name: string) => void; layout?: 'vertical' | 'horizontal' }) {
  const max = Math.max(...data.map((d) => d.value));
  if (layout === 'horizontal') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }} barCategoryGap={6}>
          <HatchDefs id="hb-h" />
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" {...axis} width={128} tick={{ fill: C.mute, fontSize: 12 }} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
          <Bar dataKey="value" name={valueName} radius={[8, 8, 8, 8]} onClick={(d: { name?: string }) => d.name && onBarClick?.(d.name)} cursor={onBarClick ? 'pointer' : undefined}>
            {data.map((d) => <Cell key={d.name} fill={d.value === max ? 'url(#hb-h)' : C.s3} stroke={d.value === max ? C.lime : 'none'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 24, right: 0, left: -18, bottom: 0 }} barCategoryGap="18%">
        <HatchDefs id="hb-v" />
        <XAxis dataKey="name" {...axis} interval={0} tick={{ fill: C.mute, fontSize: 10.5 }} tickFormatter={(v: string) => (v.length > 12 ? v.replace('Digital ', 'Digital ').split(' ').slice(0, 2).join(' ') : v)} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
        <Bar dataKey="value" name={valueName} radius={[14, 14, 14, 14]} onClick={(d: { name?: string }) => d.name && onBarClick?.(d.name)} cursor={onBarClick ? 'pointer' : undefined}
          label={{ position: 'top', fill: C.mute, fontSize: 11, formatter: (v: number) => (v === max ? fmtNum(v) : '') }}>
          {data.map((d) => <Cell key={d.name} fill={d.value === max ? 'url(#hb-v)' : C.s3} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Funnel({ data }: { data: { stage: ProspectStatus; count: number }[] }) {
  const nav = useNavigate();
  const max = data[0]?.count || 1;
  return (
    <ol className="space-y-2" aria-label="Pipeline funnel">
      {data.map((d, i) => {
        const conv = i > 0 && data[i - 1].count ? Math.round((d.count / data[i - 1].count) * 100) : null;
        const pct = Math.max(4, (d.count / max) * 100);
        return (
          <li key={d.stage}>
            <button type="button" onClick={() => nav(`/prospects?status=${d.stage}`)} className="w-full grid grid-cols-[86px_1fr_52px_44px] items-center gap-3 group text-left" aria-label={`${d.stage}: ${d.count} prospects`}>
              <span className="text-[11px] tracking-[0.08em] text-mute group-hover:text-fg">{d.stage}</span>
              <span className="h-7 rounded-full bg-s2 overflow-hidden">
                <span className={`block h-full rounded-full transition-all duration-700 ${d.stage === 'WON' ? 'bg-lime-pale' : i === data.length - 1 || d.stage === 'MEETING' ? 'hatch' : i < 2 ? 'bg-lime' : 'bg-lime-deep'}`} style={{ width: `${pct}%` }} />
              </span>
              <span className="num text-sm text-right">{fmtNum(d.count)}</span>
              <span className="text-[11px] text-dim text-right">{conv !== null ? `${conv}%` : ''}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function MultiLine({ data, keys, height = 260 }: { data: Record<string, string | number>[]; keys: { key: string; name: string; color: string; dash?: boolean }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 6, left: -18, bottom: 0 }}>
        <CartesianGrid stroke={C.line} strokeDasharray="2 6" vertical={false} />
        <XAxis dataKey="label" {...axis} minTickGap={16} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: C.mute, paddingTop: 8 }} />
        {keys.map((k) => <Line key={k.key} type="monotone" dataKey={k.key} name={k.name} stroke={k.color} strokeWidth={2} strokeDasharray={k.dash ? '4 4' : undefined} dot={false} />)}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, keys, height = 280, horizontal }: { data: Record<string, string | number>[]; keys: { key: string; name: string; color: string }[]; height?: number; horizontal?: boolean }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 10, right: 10, left: horizontal ? 8 : -18, bottom: 0 }} barGap={3}>
        <CartesianGrid stroke={C.line} strokeDasharray="2 6" vertical={!!horizontal} horizontal={!horizontal} />
        {horizontal ? <><XAxis type="number" {...axis} /><YAxis type="category" dataKey="label" {...axis} width={150} tick={{ fill: C.mute, fontSize: 11 }} /></>
          : <><XAxis dataKey="label" {...axis} interval={0} tick={{ fill: C.mute, fontSize: 10.5 }} /><YAxis {...axis} /></>}
        <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: C.mute, paddingTop: 8 }} />
        {keys.map((k) => <Bar key={k.key} dataKey={k.key} name={k.name} fill={k.color} radius={6} maxBarSize={22} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}
