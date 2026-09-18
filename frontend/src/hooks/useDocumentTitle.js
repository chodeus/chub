import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { NAV_TITLES } from '../components/navSections.js';

/** Core routes only — extension routes fall through to NAV_TITLES. Mirrors the Breadcrumbs route map. */
const ROUTE_TITLES = {
    '/login': 'Sign in',
    '/setup': 'Setup',
    '/dashboard': 'Dashboard',
    '/media/search': 'Library Search',
    '/media/manage': 'Library Management',
    '/media/statistics': 'Library Statistics',
    '/media/labelarr': 'Label Sync',
    '/poster/search/assets': 'Assets Search',
    '/poster/search/gdrive': 'GDrive Sources',
    '/poster/border-replacerr': 'Border Replacerr',
    '/poster/cleanarr': 'Poster Cleanarr',
    '/poster/manage': 'Poster Cleanarr', // legacy redirect target
    '/poster/unmatched': 'Unmatched Assets',
    '/poster/statistics': 'Poster Statistics',
    '/settings': 'Settings',
    '/settings/general': 'General Settings',
    '/settings/modules': 'Modules',
    '/settings/instances': 'Instances',
    '/settings/schedule': 'Schedule',
    '/settings/jobs': 'Jobs',
    '/settings/notifications': 'Notifications',
    '/settings/webhooks': 'Webhooks',
    '/settings/system': 'System',
    '/logs': 'Logs',
};

const SUFFIX = 'CHUB';

/** Syncs `document.title` to the route. Mount once in Layout, not per page. */
export function useDocumentTitle() {
    const { pathname } = useLocation();

    useEffect(() => {
        const label = ROUTE_TITLES[pathname] ?? NAV_TITLES[pathname];
        document.title = label ? `${label} · ${SUFFIX}` : SUFFIX;
    }, [pathname]);
}
