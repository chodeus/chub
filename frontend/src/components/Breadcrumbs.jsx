import React from 'react';
import { Link, useLocation } from 'react-router-dom';

const SEGMENT_LABELS = {
    media: 'Library',
    search: 'Search',
    manage: 'Manage',
    statistics: 'Statistics',
    labelarr: 'Label Sync',
    poster: 'Assets',
    gdrive: 'GDrive Search',
    assets: 'Assets Search',
    cleanarr: 'Poster Cleanarr',
    settings: 'Settings',
    general: 'General',
    interface: 'Interface',
    modules: 'Modules',
    instances: 'Instances',
    schedule: 'Schedule',
    jobs: 'Jobs',
    notifications: 'Notifications',
    webhooks: 'Webhooks',
    logs: 'Logs',
    dashboard: 'Dashboard',
};

const labelFor = segment =>
    SEGMENT_LABELS[segment] || segment.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

/**
 * Breadcrumb trail derived from the current URL.
 * Renders nothing for the root dashboard route.
 */
export default function Breadcrumbs() {
    const { pathname } = useLocation();
    const segments = pathname.split('/').filter(Boolean);

    if (segments.length <= 1) return null;

    const crumbs = segments.map((seg, idx) => ({
        label: labelFor(seg),
        to: '/' + segments.slice(0, idx + 1).join('/'),
        isLast: idx === segments.length - 1,
    }));

    return (
        <nav
            aria-label="Breadcrumb"
            className="flex items-center gap-1.5 text-xs text-tertiary mb-3 flex-wrap"
        >
            <Link to="/dashboard" className="no-underline hover:text-primary hover:underline">
                Home
            </Link>
            {crumbs.map(crumb => (
                <React.Fragment key={crumb.to}>
                    <span aria-hidden="true" className="text-tertiary/60">
                        /
                    </span>
                    {crumb.isLast ? (
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
            ))}
        </nav>
    );
}
