// General settings schema - separated from modules
export const GENERAL_SETTINGS_SCHEMA = [
    {
        key: 'general',
        label: 'General',
        fields: [
            {
                key: 'log_level',
                label: 'Log Level',
                type: 'dropdown',
                options: ['debug', 'info'],
                required: true,
                description: 'Set the logging verbosity for general settings.',
            },
            {
                key: 'max_logs',
                label: 'Maximum Logs',
                type: 'number',
                placeholder: '9',
                required: true,
                description: 'Set the maximum number of logs to keep.',
            },
            {
                key: 'update_notifications',
                label: 'Update Notifications',
                type: 'check_box',
                description: 'Enable notifications for available updates.',
            },
            {
                key: 'webhook_initial_delay',
                label: 'Webhook initial delay (seconds)',
                type: 'number',
                placeholder: '30',
                description:
                    'How long to wait after a webhook fires before the first Plex recently-added check. Gives Plex time to scan the new file.',
            },
            {
                key: 'webhook_retry_delay',
                label: 'Webhook retry delay (seconds)',
                type: 'number',
                placeholder: '30',
                description:
                    "How long to sleep between Plex recently-added checks if the new item still isn't visible.",
            },
            {
                key: 'webhook_max_retries',
                label: 'Webhook max retries',
                type: 'number',
                placeholder: '10',
                description:
                    'Maximum Plex recently-added checks per webhook before the upload step is skipped for this run.',
            },
        ],
    },
];
