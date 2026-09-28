import React, { useRef } from 'react';
import PropTypes from 'prop-types';

const SIZES = {
    md: 'min-h-11 px-3 text-sm',
    // 36px is a design spec, so touch-expand grows only the coarse-pointer hit area.
    sm: 'touch-expand min-h-9 min-w-11 px-2.5 text-xs',
};

/**
 * Wrapping row of chips. By default each chip toggles its own value; with `single`
 * the row is a radiogroup where onToggle selects one value and arrow keys move it.
 */
const ChipGroup = ({
    options,
    isSelected,
    onToggle,
    single = false,
    size = 'md',
    disabled = false,
    ariaLabel,
    className = '',
}) => {
    const chipRefs = useRef([]);
    const selectedIndex = options.findIndex(opt => isSelected(opt.value));
    const tabbableIndex = selectedIndex >= 0 ? selectedIndex : 0;

    // Roving tabindex plus arrow/Home/End: the keyboard contract role="radio" owes.
    const handleKeyDown = (event, index) => {
        const last = options.length - 1;
        let next = null;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
            next = index === last ? 0 : index + 1;
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
            next = index === 0 ? last : index - 1;
        } else if (event.key === 'Home') {
            next = 0;
        } else if (event.key === 'End') {
            next = last;
        }
        if (next === null) return;
        event.preventDefault();
        onToggle(options[next].value);
        chipRefs.current[next]?.focus();
    };

    return (
        <div
            // radiogroup, not tablist: a chip picks a value and owns no tabpanel, as in SegmentedControl.
            role={single ? 'radiogroup' : 'group'}
            aria-label={ariaLabel}
            className={`flex flex-wrap gap-2 ${className}`}
        >
            {options.map((opt, i) => {
                const on = isSelected(opt.value);
                const semantics = single
                    ? {
                          role: 'radio',
                          'aria-checked': on,
                          tabIndex: i === tabbableIndex ? 0 : -1,
                          onKeyDown: event => handleKeyDown(event, i),
                      }
                    : { 'aria-pressed': on };
                return (
                    <button
                        key={opt.value}
                        ref={el => {
                            chipRefs.current[i] = el;
                        }}
                        type="button"
                        disabled={disabled}
                        onClick={() => onToggle(opt.value)}
                        {...semantics}
                        className={`inline-flex items-center justify-center rounded-full border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${SIZES[size] || SIZES.md} ${
                            on
                                ? 'bg-primary/15 border-primary text-fg'
                                : 'bg-surface-inset border-border text-fg-muted hover:border-primary/50 hover:text-fg'
                        }`}
                    >
                        {opt.label}
                        {opt.count != null && (
                            <span
                                className={`ml-2 pl-2 border-l font-medium tabular-nums text-fg-subtle ${
                                    on ? 'border-primary/40' : 'border-border'
                                }`}
                            >
                                {opt.count}
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
};

ChipGroup.propTypes = {
    options: PropTypes.arrayOf(
        PropTypes.shape({
            value: PropTypes.string.isRequired,
            label: PropTypes.node.isRequired,
            count: PropTypes.number,
        })
    ).isRequired,
    isSelected: PropTypes.func.isRequired,
    onToggle: PropTypes.func.isRequired,
    single: PropTypes.bool,
    size: PropTypes.oneOf(['sm', 'md']),
    disabled: PropTypes.bool,
    ariaLabel: PropTypes.string.isRequired,
    className: PropTypes.string,
};

export default ChipGroup;
