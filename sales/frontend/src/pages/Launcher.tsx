import clsx from 'clsx';
import { ArrowUpRight, BarChart3, BookOpen, LayoutDashboard, Target, Sun, Moon } from 'lucide-react';
import { useUi } from '../store/useUi';
import { Logo } from '../components/layout/Sidebar';
import { greeting } from '../utils/format';
import { crmUrl, financeUrl, LMS_URL } from '../utils/hosts';

export interface AppDef { id: string; name: string; tag: string; desc: string; icon: React.ReactNode; url: string | null }

export const APPS: AppDef[] = [
  { id: 'crm', name: 'Lead Intelligence', tag: 'Sales CRM', desc: 'Discover companies, find decision makers, qualify and track corporate training deals.', icon: <Target size={26} />, url: crmUrl },
  { id: 'lms', name: 'Codencode Learn', tag: 'LMS', desc: 'Courses, cohorts, attendance and learner progress.', icon: <BookOpen size={26} />, url: LMS_URL },
  { id: 'finance', name: 'Finance', tag: 'Books', desc: 'Ledger, invoices, receipts and vouchers, payroll, Balance Sheet and P&L.', icon: <BarChart3 size={26} />, url: financeUrl },
  { id: 'ops', name: 'Operations', tag: 'Ops', desc: 'Class schedules, trainers, venues and daily operations.', icon: <LayoutDashboard size={26} />, url: null },
];

export default function Launcher({ onPlaceholder }: { onPlaceholder: (id: string) => void }) {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);

  return (
    <div className="min-h-screen px-4 sm:px-8 lg:px-12 py-6 bg-[radial-gradient(ellipse_at_85%_0%,rgb(var(--lime)/0.10),transparent_50%)]">
      <header className="flex items-center justify-between max-w-[1400px] mx-auto">
        <Logo />
        <button type="button" className="icon-btn" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to bright mode'}>
          {theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}
        </button>
      </header>
      <main className="max-w-[1400px] mx-auto">
        <div className="pt-14 pb-10">
          <div className="eyebrow mb-3">Codencode Workspace</div>
          <h1 className="h-display text-5xl sm:text-7xl leading-[0.95]">{greeting()}.</h1>
          <p className="text-mute mt-4 text-lg max-w-xl">Choose a program to open. Sales and Finance share one sign-in.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          {APPS.map((a, i) => {
            const cls = clsx('group relative text-left rounded-[34px] p-7 min-h-[240px] flex flex-col transition-all border hover:-translate-y-0.5',
              i === 0 ? 'bg-lime text-ink border-lime' : 'bg-s1 border-line hover:border-line2');
            const body = (
              <>
                <span className="absolute -top-px -right-px w-[86px] h-[86px] bg-bg rounded-bl-[34px]" aria-hidden />
                <span className="absolute top-1.5 right-1.5 w-[72px] h-[72px] rounded-full border flex items-center justify-center bg-bg text-fg transition-colors border-line2 group-hover:border-lime group-hover:text-lime" aria-hidden><ArrowUpRight size={22} /></span>
                <span className={clsx('w-14 h-14 rounded-2xl flex items-center justify-center', i === 0 ? 'bg-ink text-lime' : 'bg-s2 border border-line text-fg')} aria-hidden>{a.icon}</span>
                <span className={clsx('mt-auto pt-10 text-[11px] font-semibold tracking-[0.16em]', i === 0 ? 'text-ink/60' : 'text-mute')}>{a.tag.toUpperCase()}{!a.url ? ' · COMING SOON' : ''}</span>
                <span className="font-display text-[28px] leading-tight tracking-tight mt-1">{a.name}</span>
                <span className={clsx('text-sm mt-2', i === 0 ? 'text-ink/70' : 'text-mute')}>{a.desc}</span>
              </>
            );
            return a.url
              ? <a key={a.id} href={a.url} className={cls}>{body}</a>
              : <button key={a.id} type="button" onClick={() => onPlaceholder(a.id)} className={cls}>{body}</button>;
          })}
        </div>
      </main>
    </div>
  );
}

export function AppPlaceholder({ app, onBack }: { app: AppDef; onBack: () => void }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center text-center px-6">
      <span className="w-16 h-16 rounded-2xl bg-s1 border border-line flex items-center justify-center text-lime mb-6" aria-hidden>{app.icon}</span>
      <div className="eyebrow mb-2">{app.tag} · coming soon</div>
      <h1 className="h-display text-4xl sm:text-5xl">{app.name}</h1>
      <p className="text-mute mt-3 max-w-md">{app.desc} This module isn't built yet.</p>
      <button type="button" className="btn-ghost mt-8" onClick={onBack}>Back to all programs</button>
    </div>
  );
}
