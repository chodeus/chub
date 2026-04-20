import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Map of canonical pathname → user-facing page name. Kept in sync with the
 * Breadcrumbs route map so the browser tab and breadcrumb trail speak the
 * same language.
 */
const ROUTE_TITLES = {
    '/login': 'Sign in',
    '/dashboard': 'Dashboard',
    '/media/search': 'Library Search',
    '/media/manage': 'Library Management',
    '/media/statistics': 'Library Statistics',
    '/media/labelarr': 'Label Sync',
    '/poster/search/assets': 'Assets Search',
    '/poster/search/gdrive': 'GDrive Search',
    '/poster/cleanarr': 'Poster Cleanarr',
    '/poster/manage': 'Poster Cleanarr', // legacy redirect target
    '/poster/statistics': 'Poster Statistics',
    '/settings': 'Settings',
    '/settings/general': 'General Settings',
    '/settings/interface': 'Interface Settings',
    '/settings/modules': 'Modules',
    '/settings/instances': 'Instances',
    '/settings/schedule': 'Schedule',
    '/settings/jobs': 'Jobs',
    '/settings/notifications': 'Notifications',
    '/settings/webhooks': 'Webhooks',
    '/logs': 'Logs',
};

const SUFFIX = 'CHUB';

/**
 * Hook that keeps `document.title` in sync with the current route so the
 * browser tab actually tells the user which page they're on. Without this
 * every tab just reads "CHUB · Media Manager" and tab-switching is
 * useless.
 *
 * Drop it into Layout once — don't sprinkle it per page.
 */
export function useDocumentTitle() {
    const { pathname } = useLocation();

    useEffect(() => {
        const label = ROUTE_TITLES[pathname];
        document.title = label ? `${label} · ${SUFFIX}` : SUFFIX;
    }, [pathname]);
}
