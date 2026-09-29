/** Loading spinner for buttons, forms and Suspense fallbacks. */
const Spinner = ({ size = 'medium', text, className = '', center = false }) => {
    const sizeMap = {
        small: 'w-4 h-4',
        medium: 'w-6 h-6',
        large: 'w-8 h-8',
    };

    const sizeClasses = sizeMap[size] || sizeMap.medium;

    const ring = (
        <span
            className={`block shrink-0 rounded-full animate-spin ${sizeClasses} border-2 border-border border-t-primary`}
        />
    );

    if (center) {
        return (
            <div className="flex items-center justify-center p-4 min-h-content">
                <div className="flex flex-col items-center gap-3">
                    <span className={`inline-block ${className}`.trim()}>{ring}</span>
                    {text && <p className="text-sm m-0 text-fg-muted">{text}</p>}
                </div>
            </div>
        );
    }

    // One aligned unit; the label takes the surrounding font size, so set it on the caller.
    return (
        <span className={`inline-flex items-center gap-2 text-fg-muted ${className}`.trim()}>
            {ring}
            {text && <span>{text}</span>}
        </span>
    );
};

export default Spinner;
