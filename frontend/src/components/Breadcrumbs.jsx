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
// Category-level crumbs (Library / Assets / Settings) render as plain text,
// not links. They were used to route to each category's default sub-page
// (e.g. clicking "Library" from /media/manage sent you to /media/search),
// which is surprising — the crumb label reads as "current section" but
// jumping to a different route of the section just to click a label felt
// like a navigation trap. They're context, not navigation.
const ROUTE_CRUMBS = {
    '/media/search': [{ label: 'Library' }, { label: 'Search' }],
    '/media/manage': [{ label: 'Library' }, { label: 'Manage' }],
    '/media/statistics': [{ label: 'Library' }, { label: 'Statistics' }],
    '/media/labelarr': [{ label: 'Library' }, { label: 'Label Sync' }],

    '/poster/search/assets': [{ label: 'Assets' }, { label: 'Assets Search' }],
    '/poster/search/gdrive': [{ label: 'Assets' }, { label: 'GDrive Search' }],
    '/poster/cleanarr': [{ label: 'Assets' }, { label: 'Poster Cleanarr' }],
    '/poster/statistics': [{ label: 'Assets' }, { label: 'Statistics' }],

    '/settings/general': [{ label: 'Settings' }, { label: 'General' }],
    '/settings/interface': [{ label: 'Settings' }, { label: 'Interface' }],
    '/settings/modules': [{ label: 'Settings' }, { label: 'Modules' }],
    '/settings/instances': [{ label: 'Settings' }, { label: 'Instances' }],
    '/settings/schedule': [{ label: 'Settings' }, { label: 'Schedule' }],
    '/settings/jobs': [{ label: 'Settings' }, { label: 'Jobs' }],
    '/settings/notifications': [{ label: 'Settings' }, { label: 'Notifications' }],
    '/settings/webhooks': [{ label: 'Settings' }, { label: 'Webhooks' }],
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
