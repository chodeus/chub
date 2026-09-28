import React from 'react';
import PropTypes from 'prop-types';

const SIZES = {
    md: 'min-h-11 px-3 text-sm',
    // 36px is a design spec, so touch-expand grows only the coarse-pointer hit area.
    sm: 'touch-expand min-h-9 min-w-11 px-2.5 text-xs',
};

/** Wrapping row of toggle chips; each chip switches its own value on or off. */
const ChipGroup = ({
    options,
    isSelected,
    onToggle,
    size = 'md',
    disabled = false,
    ariaLabel,
    className = '',
}) => (
    <div role="group" aria-label={ariaLabel} className={`flex flex-wrap gap-2 ${className}`}>
        {options.map(opt => {
            const on = isSelected(opt.value);
            return (
                <button
                    key={opt.value}
                    type="button"
                    aria-pressed={on}
                    disabled={disabled}
                    onClick={() => onToggle(opt.value)}
                    className={`inline-flex items-center justify-center rounded-full border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${SIZES[size] || SIZES.md} ${
                        on
                            ? 'bg-primary/15 border-primary text-fg'
                            : 'bg-surface-inset border-border text-fg-muted hover:border-primary/50 hover:text-fg'
                    }`}
                >
                    {opt.label}
                </button>
            );
        })}
    </div>
);

ChipGroup.propTypes = {
    options: PropTypes.arrayOf(
        PropTypes.shape({
            value: PropTypes.string.isRequired,
            label: PropTypes.node.isRequired,
        })
    ).isRequired,
    isSelected: PropTypes.func.isRequired,
    onToggle: PropTypes.func.isRequired,
    size: PropTypes.oneOf(['sm', 'md']),
    disabled: PropTypes.bool,
    ariaLabel: PropTypes.string.isRequired,
    className: PropTypes.string,
};

export default ChipGroup;
