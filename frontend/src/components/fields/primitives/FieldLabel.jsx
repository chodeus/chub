import InfoTooltip from '../../ui/InfoTooltip.jsx';

/** Label with a required marker; `id` serves aria-labelledby, `helpText` adds an ⓘ tooltip. */
export const FieldLabel = ({ htmlFor, id, label, required = false, helpText, className = '' }) => {
    if (!label) return null;

    const labelEl = (
        <label
            id={id}
            htmlFor={htmlFor}
            className={`text-sm font-medium text-fg ${className}`.trim()}
        >
            {label}
            {required && <span className="ml-1 font-semibold text-error">*</span>}
        </label>
    );

    // No help text: keep the original single <label> (with its own bottom margin)
    // so every existing field renders byte-identically.
    if (!helpText) {
        return (
            <label
                id={id}
                htmlFor={htmlFor}
                className={`text-sm font-medium text-fg mb-1 ${className}`.trim()}
            >
                {label}
                {required && <span className="ml-1 font-semibold text-error">*</span>}
            </label>
        );
    }

    // gap-2.5 keeps the ⓘ's 44px coarse hit box off the label's own click area.
    return (
        <span className="mb-1 inline-flex items-center gap-2.5">
            {labelEl}
            <InfoTooltip text={helpText} />
        </span>
    );
};
