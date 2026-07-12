import InfoTooltip from '../../ui/InfoTooltip.jsx';

/**
 * FieldLabel Primitive Component
 *
 * Universal label component with required indicator support.
 * This primitive is composed by ALL field types for consistent labeling.
 *
 * @param {Object} props - Component props
 * @param {string} props.htmlFor - ID of the associated form control
 * @param {string} props.label - Label text to display
 * @param {boolean} [props.required=false] - Show required indicator
 * @param {string} [props.helpText] - Longer guidance revealed via an inline ⓘ tooltip
 * @param {string} [props.className=""] - Additional CSS classes
 */
export const FieldLabel = ({ htmlFor, label, required = false, helpText, className = '' }) => {
    if (!label) return null;

    const labelEl = (
        <label htmlFor={htmlFor} className={`text-sm font-medium text-fg ${className}`.trim()}>
            {label}
            {required && <span className="ml-1 font-semibold text-error">*</span>}
        </label>
    );

    // No help text: keep the original single <label> (with its own bottom margin)
    // so every existing field renders byte-identically.
    if (!helpText) {
        return (
            <label
                htmlFor={htmlFor}
                className={`text-sm font-medium text-fg mb-1 ${className}`.trim()}
            >
                {label}
                {required && <span className="ml-1 font-semibold text-error">*</span>}
            </label>
        );
    }

    return (
        <span className="mb-1 inline-flex items-center gap-1">
            {labelEl}
            <InfoTooltip text={helpText} />
        </span>
    );
};
