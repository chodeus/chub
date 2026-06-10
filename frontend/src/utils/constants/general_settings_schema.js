// General settings schema - separated from modules.
//
// The page renders one card per top-level entry; each entry's `key` is the
// config section it edits. ``user_interface`` lives here (rather than on a
// dedicated page) because it's a single setting — splitting it out earned
// its own page back when more UI knobs were planned, but in practice only
// the theme stuck.
import { SETTINGS_MODULES } from './settings_schema.js';

// Dashboard-toggleable modules = the executable modules the dashboard lists
// (backend MODULES / GET /api/modules). Derived from SETTINGS_MODULES so it
// stays in sync; tmdb + fanart are config-only and never get a dashboard card.
const DASHBOARD_MODULE_OPTIONS = SETTINGS_MODULES.filter(
    m => m.key !== 'tmdb' && m.key !== 'fanart'
).map(m => ({ value: m.key, label: m.name }));

export const GENERAL_SETTINGS_SCHEMA = [
    {
        key: 'user_interface',
        label: 'Interface',
        fields: [
            {
                key: 'theme',
                label: 'Theme',
                type: 'dropdown',
                options: ['auto', 'dark', 'light'],
                required: true,
                description: 'Choose the UI theme. Auto follows your system preference.',
            },
        ],
    },
    {
        key: 'general',
        label: 'General',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info', 'warning', 'error', 'critical'],
                required: true,
                description: 'Set the logging verbosity for general settings.',
            },
            {
                key: 'max_logs',
                label: 'Maximum Logs',
                type: 'number',
                placeholder: '9',
                min: 1,
                max: 100,
                required: true,
                description: 'Set the maximum number of logs to keep.',
            },
            {
                key: 'webhook_initial_delay',
                label: 'Webhook initial delay (seconds)',
                type: 'number',
                placeholder: '30',
                min: 0,
                max: 3600,
                description:
                    'How long to wait after a webhook fires before the first Plex recently-added check. Gives Plex time to scan the new file.',
            },
            {
                key: 'webhook_retry_delay',
                label: 'Webhook retry delay (seconds)',
                type: 'number',
                placeholder: '30',
                min: 1,
                max: 3600,
                description:
                    "How long to sleep between Plex recently-added checks if the new item still isn't visible.",
            },
            {
                key: 'webhook_max_retries',
                label: 'Webhook max retries',
                type: 'number',
                placeholder: '10',
                min: 0,
                max: 100,
                description:
                    'Maximum Plex recently-added checks per webhook before the upload step is skipped for this run.',
            },
            {
                key: 'webhook_secret',
                label: 'Webhook secret',
                type: 'password',
                placeholder: 'e.g. shared HMAC secret',
                description:
                    'Optional shared secret. When set, every inbound webhook must send `X-Webhook-Secret: <value>` (or `?secret=<value>`) or it is rejected with 401. Recommended if your webhook URL is reachable outside your LAN.',
            },
            {
                key: 'dashboard_modules',
                label: 'Dashboard Modules',
                type: 'multiselect',
                options: DASHBOARD_MODULE_OPTIONS,
                placeholder: 'Add a module…',
                description:
                    'Choose which modules appear on the dashboard, in the order you add them. Leave empty to show all modules.',
            },
            {
                key: 'dashboard_sections',
                label: 'Dashboard Sections',
                type: 'multiselect',
                options: [
                    { value: 'health', label: 'Health' },
                    { value: 'modules', label: 'Modules' },
                    { value: 'scheduler', label: 'Scheduler' },
                    { value: 'quick_start', label: 'Quick Start' },
                ],
                placeholder: 'Add a section…',
                description:
                    'Choose which dashboard sections appear, in the order you add them. Leave empty to show all in the default order.',
            },
            {
                key: 'dashboard_refresh_seconds',
                label: 'Dashboard auto-refresh (seconds)',
                type: 'number',
                placeholder: '30',
                min: 0,
                max: 3600,
                description:
                    'How often the dashboard re-polls for updates when live (SSE) updates are not connected, and how often its countdowns tick. 0 = off.',
            },
            {
                key: 'dashboard_upcoming_limit',
                label: 'Dashboard “Up next” count',
                type: 'number',
                placeholder: '5',
                min: 1,
                max: 50,
                description:
                    'How many upcoming scheduled runs to list in the Scheduler panel’s “Up next”.',
            },
            {
                key: 'duplicate_exclude_groups',
                label: 'Quality Instance Groups',
                type: 'object_array',
                displayType: 'qualityGroup',
                description:
                    'Group instances that intentionally share the same content at different qualities. Items found across instances within the same group will not be flagged as duplicates.',
                fields: [
                    {
                        key: 'instances',
                        label: 'Instances',
                        type: 'tag_input',
                        required: true,
                        allowCustom: true,
                        placeholder: 'Type instance name and press Enter...',
                        description:
                            'Enter the names of 2 or more instances that share content, such as radarr and radarr4k.',
                    },
                ],
            },
        ],
    },
];
