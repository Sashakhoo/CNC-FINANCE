import { Menu as MenuIcon, Moon, Sun } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useUi } from '../../store/useUi';
import { useMe } from '../../hooks/useAuth';
import { UserAvatar } from '../common/Avatar';

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Dashboard'], [/^\/prospects/, 'Prospects'], [/^\/companies/, 'Companies'], [/^\/contacts/, 'Contacts'],
  [/^\/discovery/, 'Discovery'], [/^\/opportunities/, 'Opportunities'], [/^\/signals/, 'Signals'], [/^\/analytics/, 'Analytics'],
  [/^\/campaigns/, 'Campaigns'], [/^\/jobs/, 'Jobs'], [/^\/settings/, 'Settings'], [/^\/providers/, 'Provider Usage'], [/^\/audit/, 'Audit Log'],
];

function ThemeToggle() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const light = theme === 'light';
  return (
    <button type="button" className="icon-btn" onClick={() => setTheme(light ? 'dark' : 'light')} aria-label={light ? 'Switch to dark mode' : 'Switch to bright mode'} title={light ? 'Dark mode' : 'Bright mode'}>
      {light ? <Moon size={17} /> : <Sun size={17} />}
    </button>
  );
}

export function Header() {
  const { pathname } = useLocation();
  const title = TITLES.find(([r]) => r.test(pathname))?.[1] ?? '';
  const setSidebar = useUi((s) => s.setSidebar);
  const me = useMe().data;

  return (
    <header className="sticky top-0 z-20 bg-bg/85 backdrop-blur-md border-b border-line">
      <div className="flex items-center gap-3 h-[72px] px-4 sm:px-6 lg:px-8">
        <button type="button" className="icon-btn lg:hidden" onClick={() => setSidebar(true)} aria-label="Open menu"><MenuIcon size={17} /></button>
        <div className="font-display text-[15px] text-mute">{title}</div>
        <div className="flex-1" />
        <ThemeToggle />
        <span className="rounded-full" title={me ? `${me.username} · ${me.role}` : undefined}><UserAvatar name={me?.username ?? '?'} size={40} /></span>
      </div>
    </header>
  );
}
