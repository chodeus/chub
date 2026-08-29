/** Read-only schema copy, not an input — carries no value, never calls onChange. */
export const NoticeField = ({ field }) => {
    const variant = field.variant === 'error' ? 'error' : 'warning';
    const tone =
        variant === 'error'
            ? 'bg-error-bg border-error/25 text-error'
            : 'bg-warning-bg border-warning/25 text-warning';

    return (
        <div role="status" className={`rounded-md border px-3 py-2 text-[12.5px] ${tone}`}>
            {field.label && <p className="font-semibold m-0 mb-1">{field.label}</p>}
            <p className="m-0 text-fg-muted">{field.description}</p>
            {field.link && (
                <a
                    href={field.link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-block mt-1 underline"
                >
                    {field.link_label || 'Learn more'}
                </a>
            )}
        </div>
    );
};
