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
        description: 'Global preferences and defaults.',
        badge: 1,
    },
    {
        to: '/settings/interface',
        icon: 'palette',
        title: 'Interface',
        description: 'Theme, density, and UI behaviour.',
        badge: 5,
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
        description: 'Discord, Notifiarr, and email alerts.',
        badge: 3,
    },
    {
        to: '/settings/webhooks',
        icon: 'webhook',
        title: 'Webhooks',
        description: 'Inbound event sources and cleanup.',
        badge: 3,
    },
];

export const SettingsSplash = React.memo(() => {
    return (
        <div className="flex flex-col gap-6">
            {/* Page Header */}
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-bold text-primary font-display m-0">Settings</h1>
                <p className="text-base text-secondary m-0">
                    Tune CHUB to match the shape of your stack.
                </p>
            </div>

            {/* Card grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {SETTINGS_CARDS.map(card => (
                    <Link
                        key={card.to}
                        to={card.to}
                        className="no-underline group block bg-surface border border-border-light rounded-lg p-5 transition-colors hover:bg-surface-alt focus:outline-none focus-visible:border-primary"
                    >
                        <div className="flex items-start gap-4">
                            <span
                                className={`badge-bubble badge-bubble--${card.badge} rounded-full w-12 h-12 shrink-0 flex items-center justify-center`}
                                aria-hidden="true"
                            >
                                <span
                                    className="material-symbols-outlined"
                                    style={{ fontSize: '24px' }}
                                >
                                    {card.icon}
                                </span>
                            </span>
                            <div className="flex flex-col gap-1 min-w-0">
                                <h2 className="text-base font-semibold text-primary m-0">
                                    {card.title}
                                </h2>
                                <p className="text-sm text-secondary m-0 leading-snug">
                                    {card.description}
                                </p>
                            </div>
                        </div>
                    </Link>
                ))}
            </div>
        </div>
    );
});

SettingsSplash.displayName = 'SettingsSplash';

export default SettingsSplash;
