import React from 'react';
import { Link } from 'react-router-dom';

/**
 * SettingsSplash - RoomSketch-style settings landing page.
 *
 * Pastel-badge cards with left-aligned content in a responsive grid.
 * Mirrors the Dashboard's quick-start aesthetic so settings doesn't feel
 * like a different app.
 */
const SETTINGS_CARDS = [
    {
        to: '/settings/general',
        icon: 'tune',
        title: 'General',
        description: 'Theme and global preferences.',
        badge: 1,
    },
    {
        to: '/settings/modules',
        icon: 'extension',
        title: 'Modules',
        description: 'Per-module configuration and options.',
        badge: 4,
    },
    {
        to: '/settings/instances',
        icon: 'dns',
        title: 'Instances',
        description: 'Radarr, Sonarr, Lidarr, and Plex connections.',
        badge: 2,
    },
    {
        to: '/settings/schedule',
        icon: 'schedule',
        title: 'Schedule',
        description: 'Automate when modules run.',
        badge: 1,
    },
    {
        to: '/settings/jobs',
        icon: 'work_history',
        title: 'Jobs',
        description: 'Monitor queued and completed runs.',
        badge: 2,
    },
    {
        to: '/settings/notifications',
        icon: 'notifications',
        title: 'Notifications',
        description: 'Discord and Notifiarr alerts.',
        badge: 3,
    },
    {
        to: '/settings/webhooks',
        icon: 'webhook',
        title: 'Webhooks',
        description: 'Inbound event sources and cleanup.',
        badge: 3,
    },
    {
        to: '/settings/system',
        icon: 'database',
        title: 'System',
        description: 'Database statistics and maintenance.',
    },
    {
        to: '/setup',
        icon: 'auto_fix_high',
        title: 'Setup Wizard',
        description: 'Re-run guided first-run setup. Pre-fills what’s configured.',
        badge: 5,
    },
];

export const SettingsSplash = React.memo(() => {
    return (
        <div className="flex flex-col gap-5">
            {/* Page Header */}
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    Settings
                </h1>
                <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                    Connections, schedules, modules, and system configuration.
                </p>
            </div>

            {/* Card grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {SETTINGS_CARDS.map(card => (
                    <Link
                        key={card.to}
                        to={card.to}
                        className="no-underline group flex items-center gap-3 bg-surface border border-border rounded-xl p-4 transition-colors hover:bg-row-hover hover:border-[#3b3d72] focus:outline-none focus-visible:border-primary"
                    >
                        <span
                            className={`badge-bubble badge-bubble--${card.badge || 1} rounded-lg w-10 h-10 shrink-0 flex items-center justify-center`}
                            aria-hidden="true"
                        >
                            <span className="material-symbols-outlined text-[20px]">
                                {card.icon}
                            </span>
                        </span>
                        <div className="flex flex-col gap-0.5 min-w-0">
                            <h2 className="font-display text-[14px] font-semibold text-fg m-0">
                                {card.title}
                            </h2>
                            <p className="text-xs text-fg-muted m-0 leading-snug truncate">
                                {card.description}
                            </p>
                        </div>
                    </Link>
                ))}
            </div>
        </div>
    );
});

SettingsSplash.displayName = 'SettingsSplash';

export default SettingsSplash;
