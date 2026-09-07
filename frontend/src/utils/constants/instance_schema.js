export const INSTANCE_SCHEMA = [
    {
        key: 'name',
        label: 'Instance Name',
        type: 'text',
        required: true,
        placeholder: 'e.g. radarr_hd',
        description: 'Unique instance name (e.g. radarr_hd)',
    },
    {
        key: 'url',
        label: 'URL',
        type: 'text',
        required: true,
        placeholder: 'http://host:port',
        description: 'Base URL for the instance (e.g. http://host:port)',
    },
    {
        key: 'api',
        label: 'API Key',
        type: 'password',
        required: true,
        placeholder: 'Paste API Key',
        description: 'API Key for this instance.',
    },
    {
        key: 'webhook_force_reupload',
        label: 'Force re-upload on webhook',
        type: 'toggle',
        // Plex doesn't fire webhooks at CHUB; the flag only matters for the
        // *arr that triggered the import.
        serviceTypes: ['radarr', 'sonarr', 'lidarr'],
        description:
            "When ON, webhooks from this instance bypass CHUB's file-hash skip and re-push the poster to Plex even if it hasn't changed on disk. Useful after a Plex wipe or while actively re-curating a library.",
    },
];
