/**
 * CHUB Notification Service Schema
 *
 * Schema definitions for notification service configurations.
 * Supports Discord, Notifiarr, and Email notification services.
 *
 * Field types used:
 * - text: Standard text input
 * - password: Secure password input
 * - number: Numeric input
 * - color: Color picker
 * - check_box: Boolean toggle
 *
 * All field types are validated against FieldRegistry.
 */

/**
 * Notification service schema definitions
 * @constant {Array<Object>} NOTIFICATIONS_SCHEMA
 *
 * @property {string} type - Service type identifier
 * @property {string} label - Display name for service
 * @property {Array<Object>} fields - Field definitions for service configuration
 *
 * Each field object contains:
 * @property {string} key - Configuration key
 * @property {string} label - Display label
 * @property {string} type - Field type from FieldRegistry
 * @property {boolean} required - Whether field is required
 * @property {string} [placeholder] - Placeholder text
 * @property {Function} [validate] - Optional validation function
 */
export const NOTIFICATIONS_SCHEMA = [
    {
        type: 'discord',
        label: 'Discord',
        fields: [
            {
                key: 'bot_name',
                label: 'Bot Name',
                type: 'text',
                required: true,
                placeholder: 'My CHUB Bot',
            },
            {
                key: 'color',
                label: 'Embed Color',
                type: 'color',
                required: false,
                default: '#ff7300',
            },
            {
                key: 'webhook',
                label: 'Webhook',
                type: 'text',
                required: true,
                placeholder: 'https://discord.com/api/webhooks/...',
                validate: v => /^https:\/\/discord(app)?\.com\/api\/webhooks\//.test(v),
            },
        ],
    },
    {
        type: 'notifiarr',
        label: 'Notifiarr',
        fields: [
            {
                key: 'color',
                label: 'Embed Color',
                type: 'color',
                required: false,
                default: '#ff7300',
            },
            {
                key: 'webhook',
                label: 'Webhook',
                type: 'text',
                required: true,
                placeholder: 'https://notifiarr.com/api/...',
                validate: v => /^https:\/\/notifiarr\.com\/api\//.test(v),
            },
            {
                key: 'channel_id',
                label: 'Channel ID',
                type: 'text',
                required: true,
                placeholder: '1234567890',
                validate: v => /^\d+$/.test(v),
            },
        ],
    },
];
