import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useState } from 'react';
import { useUi } from './store/useUi';
import { useMe, useLogout } from './hooks/useAuth';
import { isCrmMode } from './utils/hosts';
import { AppLayout } from './components/layout/AppLayout';
import { Toasts } from './components/common/Misc';
import { applyChartTheme } from './components/dashboard/Charts';
import Login from './pages/Login';
import Launcher, { APPS, AppPlaceholder } from './pages/Launcher';
import Dashboard from './pages/Dashboard';
import Prospects from './pages/Prospects';
import Contacts from './pages/Contacts';
import Companies from './pages/Companies';
import CompanyDetail from './pages/CompanyDetail';
import ContactDetail from './pages/ContactDetail';
import Settings from './pages/Settings';
import AuditLog from './pages/AuditLog';
import Discovery from './pages/Discovery';
import Campaigns, { CampaignDetail } from './pages/Campaigns';
import Analytics from './pages/Analytics';
import Jobs from './pages/Jobs';
import Providers from './pages/Providers';
import { Opportunities, Signals } from './pages/Intelligence';

function Splash({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 text-center px-6">
      <p className="text-mute max-w-md">{text}</p>
      {action}
    </div>
  );
}

export default function App() {
  const theme = useUi((s) => s.theme);
  const me = useMe();
  const logout = useLogout();
  const [placeholder, setPlaceholder] = useState<string | null>(null);
  document.documentElement.dataset.mode = theme;
  applyChartTheme(theme);

  if (!isCrmMode) {
    const app = APPS.find((a) => a.id === placeholder);
    return (<div key={theme}>{app ? <AppPlaceholder app={app} onBack={() => setPlaceholder(null)} /> : <Launcher onPlaceholder={setPlaceholder} />}<Toasts /></div>);
  }
  if (me.isPending) return <Splash text="Loading…" />;
  if (me.isError) {
    const forbidden = me.error.status === 403;
    return <Splash text={forbidden ? me.error.message : `Couldn't reach the server: ${me.error.message}`}
      action={forbidden
        ? <button type="button" className="btn-ghost" onClick={() => logout.mutate()}>Sign out</button>
        : <button type="button" className="btn-primary" onClick={() => me.refetch()}>Try again</button>} />;
  }
  if (!me.data) return (<div key={theme}><Login /><Toasts /></div>);

  return (
    <BrowserRouter key={theme} basename={window.location.pathname.startsWith('/sales') ? '/sales' : '/'}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="prospects" element={<Prospects />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="contacts/:id" element={<ContactDetail />} />
          <Route path="companies" element={<Companies />} />
          <Route path="companies/:id" element={<CompanyDetail />} />
          <Route path="settings" element={<Settings />} />
          <Route path="audit" element={<AuditLog />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="campaigns" element={<Campaigns />} />
          <Route path="campaigns/:id" element={<CampaignDetail />} />
          <Route path="discovery" element={<Discovery />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="providers" element={<Providers />} />
          <Route path="signals" element={<Signals />} />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
