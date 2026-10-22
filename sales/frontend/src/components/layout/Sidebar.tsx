import clsx from 'clsx';
import { Activity, BarChart3, Briefcase, Building2, Cog, Gauge, Grid3x3, LayoutGrid, LogOut, Megaphone, Radar, ScrollText, Target, Users, Workflow, X } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { useUi } from '../../store/useUi';
import { useMe, useLogout } from '../../hooks/useAuth';
import { launcherUrl } from '../../utils/hosts';
import { ContactAvatar } from '../common/Avatar';

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-9 h-9 rounded-xl bg-lime text-ink flex items-center justify-center font-display font-semibold text-[15px] tracking-tight" aria-hidden>c/</span>
      {!compact && (
        <div className="leading-tight">
          <div className="font-display font-semibold tracking-[0.14em] text-[13px]">CODENCODE</div>
          <div className="text-[11px] text-mute">Lead Intelligence</div>
        </div>
      )}
    </div>
  );
}

const NAV: { section?: string; items: { to: string; label: string; icon: React.ReactNode }[] }[] = [
  { items: [{ to: '/', label: 'Dashboard', icon: <LayoutGrid size={17} /> }] },
  { section: 'Sales', items: [
    { to: '/prospects', label: 'Prospects', icon: <Target size={17} /> },
    { to: '/companies', label: 'Companies', icon: <Building2 size={17} /> },
    { to: '/contacts', label: 'Contacts', icon: <Users size={17} /> },
  ] },
  { section: 'Intelligence', items: [
    { to: '/discovery', label: 'Discovery', icon: <Radar size={17} /> },
    { to: '/opportunities', label: 'Opportunities', icon: <Briefcase size={17} /> },
    { to: '/signals', label: 'Signals', icon: <Activity size={17} /> },
  ] },
  { section: 'Analytics', items: [{ to: '/analytics', label: 'Analytics', icon: <BarChart3 size={17} /> }] },
  { section: 'Outreach', items: [{ to: '/campaigns', label: 'Campaigns', icon: <Megaphone size={17} /> }] },
  { section: 'Automation', items: [{ to: '/jobs', label: 'Jobs', icon: <Workflow size={17} /> }] },
  { section: 'System', items: [
    { to: '/settings', label: 'Settings', icon: <Cog size={17} /> },
    { to: '/providers', label: 'Provider Usage', icon: <Gauge size={17} /> },
    { to: '/audit', label: 'Audit Log', icon: <ScrollText size={17} /> },
  ] },
];

export function Sidebar() {
  const open = useUi((s) => s.sidebarOpen);
  const setOpen = useUi((s) => s.setSidebar);
  const ask = useUi((s) => s.ask);
  const toast = useUi((s) => s.toast);
  const me = useMe().data;
  const logout = useLogout();

  return (
    <>
      {open && <div className="fixed inset-0 bg-black/60 z-30 lg:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={clsx('fixed lg:sticky top-0 left-0 z-40 h-screen w-[248px] shrink-0 bg-bg border-r border-line flex flex-col transition-transform lg:translate-x-0', open ? 'translate-x-0' : '-translate-x-full')}
        aria-label="Primary navigation">
        <div className="flex items-center justify-between px-5 h-[72px]">
          <a href={launcherUrl} className="rounded-xl" aria-label="All programs" title="All programs"><Logo /></a>
          <button type="button" className="icon-btn-sm lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X size={15} /></button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          <a href={launcherUrl} className="w-full flex items-center gap-3 h-10 px-3 rounded-full text-sm text-mute hover:text-fg hover:bg-s2 border border-dashed border-line mb-2"><Grid3x3 size={17} aria-hidden />All programs</a>
          {NAV.map((g, i) => (
            <div key={i} className="mt-3 first:mt-1">
              {g.section && <div className="px-3 pb-1.5 pt-2 text-[10px] font-medium tracking-[0.16em] uppercase text-dim">{g.section}</div>}
              {g.items.map((it) => (
                <NavLink key={it.to} to={it.to} end={it.to === '/'} onClick={() => setOpen(false)}
                  className={({ isActive }) => clsx('flex items-center gap-3 h-10 px-3 rounded-full text-sm transition-colors mb-0.5',
                    isActive ? 'bg-fg text-bg font-medium' : 'text-mute hover:text-fg hover:bg-s2')}>
                  {({ isActive }) => (
                    <>
                      <span className={isActive ? 'text-bg' : ''} aria-hidden>{it.icon}</span>
                      <span className="flex-1">{it.label}</span>
                      {isActive && <span className="w-1.5 h-1.5 rounded-full bg-lime" aria-hidden />}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="p-3 border-t border-line">
          <div className="flex items-center gap-3 p-2 rounded-2xl bg-s1 border border-line">
            <ContactAvatar name={me?.username ?? '?'} size={36} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{me?.username}</div>
              <div className="text-[11px] text-mute capitalize">{me?.role.toLowerCase()}</div>
            </div>
            <button type="button" className="icon-btn-sm" aria-label="Log out"
              onClick={() => ask({ title: 'Log out?', message: 'This signs you out of Sales and Finance.', confirmLabel: 'Log out', onConfirm: () => logout.mutate(undefined, { onSuccess: () => toast('Signed out', 'info') }) })}>
              <LogOut size={14} />
            </button>
          </div>
          <p className="mt-2 px-1 text-[10px] text-dim leading-snug">
            Avatars: <a className="underline" href="https://www.dicebear.com/styles/micah/" target="_blank" rel="noopener noreferrer">Micah</a> by Micah Lanier,{' '}
            <a className="underline" href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a> (via DiceBear)
          </p>
        </div>
      </aside>
    </>
  );
}
