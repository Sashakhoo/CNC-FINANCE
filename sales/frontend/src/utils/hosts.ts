// main.<domain> = launcher, sales.<domain> = CRM. On any other host
// (localhost, the Railway URL) the same pages live at /launcher and /sales.
const { protocol, host, pathname } = window.location;
const lower = host.toLowerCase();
const onMain = lower.startsWith('main.');
const onSales = lower.startsWith('sales.');
const root = onMain ? host.slice(5) : onSales ? host.slice(6) : null;

export const isCrmMode = onSales || pathname.startsWith('/sales');

export const launcherUrl = root ? `${protocol}//main.${root}/` : '/launcher';
export const crmUrl = root ? `${protocol}//sales.${root}/` : '/sales';
export const financeUrl = root ? `${protocol}//finance.${root}/` : '/finance';
export const LMS_URL = 'https://learn.codencode.my';
