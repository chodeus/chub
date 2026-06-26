import { Button } from '../ui/button/Button';

// Channel-type identity colour + tint for the avatar / type pill.
const TYPE_STYLE = {
    discord: ['#a99eff', 'rgba(135,103,247,.16)'],
    notifiarr: ['#53e8f0', 'rgba(83,232,240,.14)'],
    email: ['#6cbc66', 'rgba(108,188,102,.14)'],
    webhook: ['#ffc944', 'rgba(255,201,68,.14)'],
    telegram: ['#53e8f0', 'rgba(83,232,240,.14)'],
};

const LABELS = {
    discord: 'Discord',
    notifiarr: 'Notifiarr',
    email: 'Email',
    webhook: 'Webhook',
    telegram: 'Telegram',
};

/**
 * NotificationCard — compact channel row: icon tile, name + type pill, target,
 * optional on-success/on-failure trigger pills, and Test / Edit / Delete.
 */
export const NotificationCard = ({
    moduleName,
    serviceType,
    config = {},
    onEdit,
    onDelete,
    onTest,
    isTesting = false,
}) => {
    const [color, tint] = TYPE_STYLE[serviceType] || ['#8ea3cc', 'rgba(101,130,202,.14)'];
    const name = LABELS[serviceType] || serviceType;
    const initial = name.charAt(0).toUpperCase();
    const target =
        serviceType === 'discord'
            ? config.bot_name || 'Not set'
            : serviceType === 'notifiarr'
              ? `channel ${config.channel_id || '—'}`
              : config.target || config.url || config.email || '';
    const onSuccess = config.notify_on_success ?? config.on_success;
    const onFailure = config.notify_on_failure ?? config.on_failure;
    const iconBtn =
        'w-8 h-8 rounded-lg flex items-center justify-center text-fg-muted hover:text-fg hover:bg-row-hover transition-colors';

    return (
        <div className="flex items-center gap-[15px] px-[18px] py-4 rounded-xl bg-surface border border-border hover:border-[#3b3d72] transition-colors">
            <span
                className="shrink-0 w-[42px] h-[42px] rounded-[10px] flex items-center justify-center font-display text-[16px] font-bold"
                style={{ background: tint, color }}
                aria-hidden="true"
            >
                {initial}
            </span>

            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="font-display text-[15px] font-semibold text-fg truncate">
                        {name}
                    </span>
                    <span
                        className="shrink-0 font-mono text-[9px] uppercase tracking-[0.4px] px-1.5 py-0.5 rounded-[5px]"
                        style={{ color, background: tint }}
                    >
                        {serviceType}
                    </span>
                </div>
                {target && (
                    <div
                        className="font-mono text-[11.5px] text-fg-subtle mt-1 truncate"
                        title={target}
                    >
                        {target}
                    </div>
                )}
            </div>

            {(onSuccess != null || onFailure != null) && (
                <div className="hidden sm:flex items-center gap-1.5 shrink-0">
                    {onSuccess != null && (
                        <span
                            className={`font-mono text-[9.5px] font-semibold px-[9px] py-1 rounded-full ${
                                onSuccess
                                    ? 'bg-success/[0.13] text-success'
                                    : 'bg-surface-inset text-fg-faint'
                            }`}
                        >
                            on success
                        </span>
                    )}
                    {onFailure != null && (
                        <span className="font-mono text-[9.5px] font-semibold px-[9px] py-1 rounded-full bg-error/[0.13] text-error">
                            on failure
                        </span>
                    )}
                </div>
            )}

            <div className="flex items-center gap-1.5 shrink-0">
                <Button
                    variant="surface"
                    size="small"
                    onClick={() => onTest(moduleName, serviceType, config)}
                    disabled={isTesting}
                >
                    {isTesting ? 'Testing…' : 'Test'}
                </Button>
                <button
                    type="button"
                    onClick={() => onEdit(moduleName, serviceType, config)}
                    className={iconBtn}
                    aria-label="Edit channel"
                    title="Edit"
                >
                    <span className="material-symbols-outlined text-[18px]">edit</span>
                </button>
                <button
                    type="button"
                    onClick={() => onDelete(moduleName, serviceType)}
                    className={`${iconBtn} hover:text-error`}
                    aria-label="Delete channel"
                    title="Delete"
                >
                    <span className="material-symbols-outlined text-[18px]">delete</span>
                </button>
            </div>
        </div>
    );
};
