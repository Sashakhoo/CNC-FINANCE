import { Radar } from 'lucide-react';
import { useState } from 'react';
import clsx from 'clsx';
import { DEPARTMENTS, INDUSTRIES, LOCATIONS, TITLE_NAMES } from '../../data/constants';
import { Field, Switch, ToggleChips } from '../common/Form';

export interface SearchCriteria {
  country: string; state: string | null; city: string | null; industries: string[]; size_min: number; size_max: number;
  departments: string[]; titles: string[]; min_lead_score: number; max_companies: number; seed_websites: string[];
  find_profiles: boolean; schedule: 'weekly' | null;
}
export interface SearchDraft { name: string; criteria: SearchCriteria }

export const DEFAULT_SEARCH: SearchDraft = {
  name: 'Johor Engineering Prospects',
  criteria: {
    country: 'Malaysia', state: 'Johor', city: null, industries: ['Manufacturing', 'Engineering', 'Electrical', 'Electronics', 'Automation'],
    size_min: 30, size_max: 1000, departments: ['HR', 'L&D', 'IT', 'Engineering'],
    titles: ['HR Manager', 'L&D Manager', 'Training Manager', 'IT Manager', 'Head of IT', 'Engineering Manager', 'Digital Transformation Manager', 'Managing Director'],
    min_lead_score: 60, max_companies: 20, seed_websites: [], find_profiles: true, schedule: null,
  },
};

function Section({ n, title, children, hint }: { n: string; title: string; children: React.ReactNode; hint?: string }) {
  return (
    <section className="grid lg:grid-cols-[220px_1fr] gap-4 lg:gap-8 py-6 border-b border-line last:border-0">
      <div>
        <div className="flex items-center gap-3"><span className="num text-lime text-sm">{n}</span><h3 className="eyebrow text-fg">{title}</h3></div>
        {hint && <p className="text-xs text-mute mt-2 lg:pl-7">{hint}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export function DiscoveryForm({ initial, onSubmit, onCancel, busy, searchConfigured }: {
  initial?: SearchDraft; onSubmit: (d: SearchDraft) => void; onCancel: () => void; busy?: boolean; searchConfigured: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? DEFAULT_SEARCH.name);
  const [c, setC] = useState<SearchCriteria>(initial?.criteria ?? DEFAULT_SEARCH.criteria);
  const [seeds, setSeeds] = useState((initial?.criteria.seed_websites ?? []).join('\n'));
  const set = <K extends keyof SearchCriteria>(k: K, v: SearchCriteria[K]) => setC((x) => ({ ...x, [k]: v }));
  const states = Array.from(new Set(LOCATIONS.filter((l) => l.country === c.country).map((l) => l.state)));
  const cities = LOCATIONS.filter((l) => l.country === c.country && (!c.state || l.state === c.state)).map((l) => l.city);
  const sizePct = (v: number) => ((v - 10) / (2000 - 10)) * 100;
  const seedList = seeds.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
  const blocked = !searchConfigured && !seedList.length;

  return (
    <form className="card px-5 sm:px-8 py-2" aria-label="New prospect search"
      onSubmit={(e) => { e.preventDefault(); onSubmit({ name: name.trim() || 'Untitled search', criteria: { ...c, seed_websites: seedList } }); }}>
      <Section n="01" title="Search name" hint="Shown on the Jobs page and in saved searches.">
        <input aria-label="Search name" className="input h-11 max-w-xl" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </Section>

      <Section n="02" title="Location">
        <div className="grid sm:grid-cols-3 gap-3 max-w-2xl">
          <Field label="Country" htmlFor="d-country">
            <select id="d-country" className="input" value={c.country} onChange={(e) => { const country = e.target.value; setC((x) => ({ ...x, country, state: LOCATIONS.find((l) => l.country === country)!.state, city: null })); }}>
              {['Malaysia', 'Singapore'].map((x) => <option key={x}>{x}</option>)}
            </select>
          </Field>
          <Field label="State" htmlFor="d-state">
            <select id="d-state" className="input" value={c.state ?? ''} onChange={(e) => setC((x) => ({ ...x, state: e.target.value || null, city: null }))}>
              {c.country === 'Malaysia' && <option value="">All states</option>}
              {states.map((x) => <option key={x}>{x}</option>)}
            </select>
          </Field>
          <Field label="City" htmlFor="d-city">
            <select id="d-city" className="input" value={c.city ?? ''} onChange={(e) => set('city', e.target.value || null)}>
              <option value="">All cities</option>{cities.map((x) => <option key={x}>{x}</option>)}
            </select>
          </Field>
        </div>
      </Section>

      <Section n="03" title="Industries">
        <ToggleChips label="Industries" options={INDUSTRIES} value={c.industries} onChange={(v) => set('industries', v)} />
      </Section>

      <Section n="04" title="Company size" hint="Used in the lead score. Company size is often unknown until found on the website.">
        <div className="max-w-xl">
          <div className="flex items-baseline justify-between mb-3"><span className="num text-2xl">{c.size_min} — {c.size_max >= 2000 ? '2,000+' : c.size_max.toLocaleString()}</span><span className="text-xs text-mute">employees</span></div>
          <div className="relative h-6">
            <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-1.5 rounded-full bg-line" />
            <div className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-lime" style={{ left: `${sizePct(c.size_min)}%`, right: `${100 - sizePct(c.size_max)}%` }} />
            <input type="range" aria-label="Minimum employees" min={10} max={2000} step={10} value={c.size_min} onChange={(e) => set('size_min', Math.min(Number(e.target.value), c.size_max - 20))} className="dual absolute inset-0 w-full" />
            <input type="range" aria-label="Maximum employees" min={10} max={2000} step={10} value={c.size_max} onChange={(e) => set('size_max', Math.max(Number(e.target.value), c.size_min + 20))} className="dual absolute inset-0 w-full" />
          </div>
        </div>
      </Section>

      <Section n="05" title="Target departments" hint="Decision makers from these departments are kept; others are skipped.">
        <ToggleChips label="Target departments" options={DEPARTMENTS} value={c.departments} onChange={(v) => set('departments', v)} />
      </Section>

      <Section n="06" title="Target titles" hint="Optional. When set, only people whose title normalizes to one of these are kept.">
        <ToggleChips label="Target titles" options={TITLE_NAMES} value={c.titles} onChange={(v) => set('titles', v)} />
      </Section>

      <Section n="07" title="Minimum lead score" hint="Prospects below this are still kept for review, just ranked lower.">
        <div className="flex items-center gap-5 max-w-xl">
          <input type="range" aria-label="Minimum lead score" min={0} max={100} value={c.min_lead_score} onChange={(e) => set('min_lead_score', Number(e.target.value))} className="flex-1" />
          <span className="num text-3xl w-14 text-right text-lime">{c.min_lead_score}</span>
        </div>
      </Section>

      <Section n="08" title="Maximum companies" hint="Start small (20–50) to check data quality before scaling up.">
        <div role="radiogroup" aria-label="Maximum companies" className="flex flex-wrap gap-2">
          {[10, 20, 50, 100, 250, 500].map((n) => (
            <button key={n} type="button" role="radio" aria-checked={c.max_companies === n} onClick={() => set('max_companies', n)}
              className={clsx('h-10 px-5 rounded-full text-sm border num', c.max_companies === n ? 'bg-fg text-bg border-fg' : 'bg-s2 border-line text-mute hover:text-fg')}>{n}</button>
          ))}
        </div>
      </Section>

      <Section n="09" title="Company websites" hint={searchConfigured ? 'Optional: also process these sites directly (one per line).' : 'No search provider is configured — list company websites to process (one per line).'}>
        <textarea aria-label="Company websites" className="input h-28 py-2 max-w-xl font-mono text-xs" value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder={'southern-precision.com.my\nhttps://example-automation.com.my'} />
        <p className="text-xs text-dim mt-2">{seedList.length} website{seedList.length === 1 ? '' : 's'} · only public pages permitted by robots.txt are fetched.</p>
      </Section>

      <Section n="10" title="Options">
        <div className="space-y-3 max-w-xl text-sm">
          <label className="flex items-center gap-3"><Switch checked={c.find_profiles} onChange={(v) => set('find_profiles', v)} label="Find professional profiles" />
            Look up public professional profile links through the search provider (uses search quota)</label>
          <label className="flex items-center gap-3"><Switch checked={c.schedule === 'weekly'} onChange={(v) => set('schedule', v ? 'weekly' : null)} label="Run weekly" />
            Re-run this search every Monday to find new companies</label>
        </div>
      </Section>

      <div className="flex flex-wrap items-center justify-end gap-2 py-6">
        {blocked && <span className="text-xs text-amber mr-auto">Configure a search provider in Settings → Providers, or list websites above.</span>}
        <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={busy || blocked || !c.departments.length}><Radar size={16} />Start discovery</button>
      </div>
    </form>
  );
}
