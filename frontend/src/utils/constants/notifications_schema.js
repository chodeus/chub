/** Discord and Notifiarr config schemas. Every `type` must exist in FieldRegistry. */
export const NOTIFICATIONS_SCHEMA = [
    {
        type: 'discord',
        label: 'Discord',
        fields: [
            {
                key: 'bot_name',
                label: 'Bot Name',
                type: 'text',
                required: false,
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
                type: 'password',
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
                type: 'password',
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
