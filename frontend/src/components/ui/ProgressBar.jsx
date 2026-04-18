/**
 * ProgressBar - Reusable progress indicator component
 *
 * Displays a horizontal progress bar with optional label and percentage.
 * Used for tracking module execution progress, batch operations, etc.
 *
 * @param {Object} props - Component props
 * @param {number} [props.value=0] - Progress value (0-100)
 * @param {string} [props.label] - Optional label text above the bar
 * @param {string} [props.size='medium'] - Bar height: 'small', 'medium', 'large'
 * @param {boolean} [props.showPercent=true] - Show percentage text
 * @param {boolean} [props.animate=true] - Animate the bar fill transitions
 * @param {string} [props.className] - Additional CSS classes
 * @returns {JSX.Element} ProgressBar component
 */
const ProgressBar = ({
    value = 0,
    label,
    size = 'medium',
    showPercent = true,
    animate = true,
    className = '',
}) => {
    const clampedValue = Math.max(0, Math.min(100, value));

    const sizeMap = {
        small: 'h-1',
        medium: 'h-2',
        large: 'h-3',
    };

    const barHeight = sizeMap[size] || sizeMap.medium;

    return (
        <div className={`w-full ${className}`.trim()}>
            {(label || showPercent) && (
                <div className="flex items-center justify-between mb-1">
                    {label && <span className="text-xs text-secondary truncate">{label}</span>}
                    {showPercent && (
                        <span className="text-xs text-secondary ml-2 tabular-nums">
                            {Math.round(clampedValue)}%
                        </span>
                    )}
                </div>
            )}
            <div className={`w-full ${barHeight} bg-surface-alt rounded-full overflow-hidden`}>
                <div
                    className={`${barHeight} bg-primary rounded-full ${animate ? 'transition-all duration-300 ease-out' : ''}`}
                    style={{ width: `${clampedValue}%` }}
                />
            </div>
        </div>
    );
};

export default ProgressBar;
