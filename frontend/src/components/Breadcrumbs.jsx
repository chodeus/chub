import React from 'react';
import { Link, useLocation } from 'react-router-dom';

/**
 * Per-route crumb chains so deep routes like /poster/search/assets render as
 * "Home / Assets / Assets Search" rather than "Home / Poster / Search /
 * Assets" which reveals internal URL structure users don't care about.
 *
 * Keys are exact pathnames. Values are ordered crumbs (leftmost first); the
 * last entry is always treated as "current" and rendered without a link.
 */
const ROUTE_CRUMBS = {
    '/media/search': [{ label: 'Library', to: '/media/search' }, { label: 'Search' }],
    '/media/manage': [{ label: 'Library', to: '/media/search' }, { label: 'Manage' }],
    '/media/statistics': [{ label: 'Library', to: '/media/search' }, { label: 'Statistics' }],
    '/media/labelarr': [{ label: 'Library', to: '/media/search' }, { label: 'Label Sync' }],

    '/poster/search/assets': [
        { label: 'Assets', to: '/poster/search/assets' },
        { label: 'Assets Search' },
    ],
    '/poster/search/gdrive': [
        { label: 'Assets', to: '/poster/search/assets' },
        { label: 'GDrive Search' },
    ],
    '/poster/manage': [
        { label: 'Assets', to: '/poster/search/assets' },
        { label: 'Poster Cleanarr' },
    ],
    '/poster/statistics': [
        { label: 'Assets', to: '/poster/search/assets' },
        { label: 'Statistics' },
    ],

    '/settings/general': [{ label: 'Settings', to: '/settings/general' }, { label: 'General' }],
    '/settings/interface': [{ label: 'Settings', to: '/settings/general' }, { label: 'Interface' }],
    '/settings/modules': [{ label: 'Settings', to: '/settings/general' }, { label: 'Modules' }],
    '/settings/instances': [{ label: 'Settings', to: '/settings/general' }, { label: 'Instances' }],
    '/settings/schedule': [{ label: 'Settings', to: '/settings/general' }, { label: 'Schedule' }],
    '/settings/jobs': [{ label: 'Settings', to: '/settings/general' }, { label: 'Jobs' }],
    '/settings/notifications': [
        { label: 'Settings', to: '/settings/general' },
        { label: 'Notifications' },
    ],
    '/settings/webhooks': [{ label: 'Settings', to: '/settings/general' }, { label: 'Webhooks' }],
};

// Routes where breadcrumbs add no value (the PageHeader already names them
// and they're top-level sidebar entries).
const SKIP_ROUTES = new Set(['/', '/dashboard', '/logs', '/login']);

export default function Breadcrumbs() {
    const { pathname } = useLocation();
    if (SKIP_ROUTES.has(pathname)) return null;

    const crumbs = ROUTE_CRUMBS[pathname];
    if (!crumbs || crumbs.length === 0) return null;

    return (
        <nav
            aria-label="Breadcrumb"
            className="flex items-center gap-1.5 text-xs text-tertiary mb-3 flex-wrap"
        >
            <Link to="/dashboard" className="no-underline hover:text-primary hover:underline">
                Home
            </Link>
            {crumbs.map((crumb, idx) => {
                const isLast = idx === crumbs.length - 1;
                return (
                    <React.Fragment key={`${crumb.label}-${idx}`}>
                        <span aria-hidden="true" className="text-tertiary/60">
                            /
                        </span>
                        {isLast || !crumb.to ? (
                            <span aria-current="page" className="text-secondary">
                                {crumb.label}
                            </span>
                        ) : (
                            <Link
                                to={crumb.to}
                                className="no-underline hover:text-primary hover:underline"
                            >
                                {crumb.label}
                            </Link>
                        )}
                    </React.Fragment>
                );
            })}
        </nav>
    );
}
