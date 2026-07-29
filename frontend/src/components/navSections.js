import { withExtensionNavChildren } from '../extensions/index.js';

const CORE_NAV_SECTIONS = [
    {
        id: 'home',
        heading: null,
        items: [
            {
                id: 'dashboard',
                label: 'Dashboard',
                path: '/dashboard',
                icon: 'home',
                type: 'single',
            },
        ],
    },
    {
        id: 'media',
        heading: 'Media',
        items: [
            {
                id: 'media',
                label: 'Library',
                path: '/media',
                icon: 'movie',
                type: 'parent',
                children: [
                    { id: 'media-search', label: 'Search', path: '/media/search' },
                    { id: 'media-manage', label: 'Manage', path: '/media/manage' },
                    { id: 'media-statistics', label: 'Statistics', path: '/media/statistics' },
                    { id: 'media-labelarr', label: 'Label Sync', path: '/media/labelarr' },
                ],
            },
        ],
    },
    {
        id: 'posters',
        heading: 'Posters',
        items: [
            {
                id: 'poster',
                label: 'Assets',
                path: '/poster',
                icon: 'image',
                type: 'parent',
                children: [
                    { id: 'gdrive-search', label: 'GDrive Sources', path: '/poster/search/gdrive' },
                    { id: 'assets-search', label: 'Assets Search', path: '/poster/search/assets' },
                    { id: 'poster-cleanarr', label: 'Poster Cleanarr', path: '/poster/cleanarr' },
                    {
                        id: 'border-replacerr',
                        label: 'Border Replacerr',
                        path: '/poster/border-replacerr',
                    },
                    {
                        id: 'unmatched-assets',
                        label: 'Unmatched Assets',
                        path: '/poster/unmatched',
                    },
                    { id: 'poster-statistics', label: 'Statistics', path: '/poster/statistics' },
                ],
            },
        ],
    },
    {
        id: 'system',
        heading: 'System',
        items: [
            {
                id: 'settings',
                label: 'Settings',
                path: '/settings',
                icon: 'settings',
                type: 'parent',
                children: [
                    { id: 'settings-general', label: 'General', path: '/settings/general' },
                    { id: 'settings-modules', label: 'Modules', path: '/settings/modules' },
                    { id: 'settings-instances', label: 'Instances', path: '/settings/instances' },
                    { id: 'settings-schedule', label: 'Schedule', path: '/settings/schedule' },
                    { id: 'settings-jobs', label: 'Jobs', path: '/settings/jobs' },
                    {
                        id: 'settings-notifications',
                        label: 'Notifications',
                        path: '/settings/notifications',
                    },
                    { id: 'settings-webhooks', label: 'Webhooks', path: '/settings/webhooks' },
                    { id: 'settings-system', label: 'System', path: '/settings/system' },
                ],
            },
            {
                id: 'logs',
                label: 'Logs',
                path: '/logs',
                icon: 'description',
                type: 'single',
            },
        ],
    },
];

// Extension nav children (src/extensions) spliced in — identity on main.
export const NAV_SECTIONS = withExtensionNavChildren(CORE_NAV_SECTIONS);

/**
 * pathname → nav label, derived from the sections above so it covers extension
 * routes too. The page-title maps are hand-written and only know core routes,
 * which left extension pages with a blank mobile header and a bare "CHUB" tab
 * title; they fall back to this rather than needing an entry per extension.
 */
export const NAV_TITLES = Object.fromEntries(
    NAV_SECTIONS.flatMap(section =>
        section.items.flatMap(item => [
            [item.path, item.label],
            ...(item.children ?? []).map(child => [child.path, child.label]),
        ])
    )
);
