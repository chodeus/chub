import React, { useRef } from 'react';
import PropTypes from 'prop-types';

/** Pill row of mutually-exclusive options, exposed as a radiogroup with arrow-key navigation. */
const SegmentedControl = ({
    options,
    value,
    onChange,
    size = 'md',
    className = '',
    fullWidth = false,
    ariaLabel,
}) => {
    const wrapH = size === 'sm' ? 'h-9' : 'h-11';
    // min-w-11 pins touch-expand's 44px box to the segment's own width, so a
    // one-character schema label can't reach across gap-0.5 into its neighbour.
    const segH = size === 'sm' ? 'h-7 min-w-11 px-3 text-xs' : 'h-9 min-w-11 px-3.5 text-[13px]';
    const wrapLayout = fullWidth ? 'flex w-full' : 'inline-flex';
    const segFlex = fullWidth ? 'flex-1' : '';

    const segmentRefs = useRef([]);
    const activeIndex = options.findIndex(o => o.value === value);
    // Roving tabindex: one segment in the Tab order, arrows move within the group.
    const tabbableIndex = activeIndex >= 0 ? activeIndex : 0;

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
        // Radios select on arrow, not just focus.
        event.preventDefault();
        onChange(options[next].value);
        segmentRefs.current[next]?.focus();
    };

    return (
        <div
            className={`${wrapLayout} items-center ${wrapH} p-1 gap-0.5 rounded-[10px] bg-surface-inset border border-border ${className}`}
            // radiogroup, not tablist: these pick a value, and no segment controls a tabpanel.
            role="radiogroup"
            aria-label={ariaLabel}
        >
            {options.map((opt, i) => {
                const active = opt.value === value;
                // `danger` marks a destructive option (e.g. a Remove mode): red
                // when selected, red-tinted text when not — distinct from the
                // brand-violet active state of normal options.
                const stateCls = active
                    ? opt.danger
                        ? 'bg-error text-white font-semibold'
                        : 'bg-primary text-on-color font-semibold'
                    : opt.danger
                      ? 'text-error font-medium hover:brightness-110'
                      : 'text-fg-muted font-medium hover:text-fg';
                return (
                    <button
                        key={opt.value}
                        ref={el => {
                            segmentRefs.current[i] = el;
                        }}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        tabIndex={i === tabbableIndex ? 0 : -1}
                        onKeyDown={e => handleKeyDown(e, i)}
                        onClick={() => onChange(opt.value)}
                        className={`touch-expand inline-flex items-center justify-center ${segFlex} ${segH} rounded-[7px] whitespace-nowrap transition-colors cursor-pointer ${stateCls}`}
                    >
                        {opt.label}
                    </button>
                );
            })}
        </div>
    );
};

SegmentedControl.propTypes = {
    options: PropTypes.arrayOf(
        PropTypes.shape({
            value: PropTypes.string.isRequired,
            label: PropTypes.node.isRequired,
            danger: PropTypes.bool,
        })
    ).isRequired,
    value: PropTypes.string,
    onChange: PropTypes.func.isRequired,
    size: PropTypes.oneOf(['sm', 'md']),
    className: PropTypes.string,
    fullWidth: PropTypes.bool,
    // A radiogroup with no accessible name is the bug this prop exists to prevent,
    // so an empty string has to fail as hard as a missing one.
    ariaLabel: (props, propName, componentName) =>
        typeof props[propName] === 'string' && props[propName].trim() !== ''
            ? null
            : new Error(`${componentName}: ariaLabel must be a non-empty string.`),
};

export default SegmentedControl;
