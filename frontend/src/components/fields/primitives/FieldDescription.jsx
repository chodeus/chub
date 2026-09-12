/** Help text under a field control; `id` is the aria-describedby target. Renders nothing when empty. */
export const FieldDescription = ({ id, description, className = '' }) => {
    if (!description) return null;

    return (
        <div id={id} className={`text-xs text-fg-muted mt-1 ${className}`.trim()}>
            {description}
        </div>
    );
};
