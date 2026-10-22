import { Outlet, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { useUi } from '../../store/useUi';
import { ConfirmDialog } from '../common/Overlay';
import { Toasts } from '../common/Misc';

export function AppLayout() {
  const confirm = useUi((s) => s.confirm);
  const closeConfirm = useUi((s) => s.closeConfirm);
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[80] btn-primary">Skip to content</a>
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <Header />
        <main id="main" className="flex-1 px-4 sm:px-6 lg:px-8 py-6 lg:py-8 max-w-[1680px] w-full mx-auto animate-fadein" key={pathname.split('/')[1]}>
          <Outlet />
        </main>
      </div>
      {confirm && <ConfirmDialog open title={confirm.title} message={confirm.message} confirmLabel={confirm.confirmLabel} danger={confirm.danger} onConfirm={confirm.onConfirm} onClose={closeConfirm} />}
      <Toasts />
    </div>
  );
}
