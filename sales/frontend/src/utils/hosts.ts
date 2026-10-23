// main.<domain> = launcher, crm.<domain> = CRM (sales.<domain> still works
// as an alias). On any other host (localhost, the Railway URL) the same pages
// live at /launcher and /sales.
const { protocol, host, pathname } = window.location;
const lower = host.toLowerCase();
const onMain = lower.startsWith('main.');
const crmPrefix = lower.startsWith('crm.') ? 'crm.' : lower.startsWith('sales.') ? 'sales.' : null;
const root = onMain ? host.slice(5) : crmPrefix ? host.slice(crmPrefix.length) : null;

export const isCrmMode = crmPrefix !== null || pathname.startsWith('/sales');

export const launcherUrl = root ? `${protocol}//main.${root}/` : '/launcher';
export const crmUrl = root ? `${protocol}//crm.${root}/` : '/sales';
export const financeUrl = root ? `${protocol}//finance.${root}/` : '/finance';
export const LMS_URL = 'https://learn.codencode.my';
