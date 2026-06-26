import React from 'react';
import PropTypes from 'prop-types';

/**
 * Segmented control — a pill row of mutually-exclusive options. The active
 * segment fills with the brand colour; inactive segments are muted text that
 * brightens on hover. Used for type/scope/mode toggles across the redesign.
 *
 * @param {Array<{value: string, label: React.ReactNode}>} options
 * @param {string} value - currently-selected option value
 * @param {(value: string) => void} onChange
 * @param {'sm'|'md'} [size]
 */
const SegmentedControl = ({ options, value, onChange, size = 'md', className = '' }) => {
    const wrapH = size === 'sm' ? 'h-9' : 'h-11';
    const segH = size === 'sm' ? 'h-7 px-3 text-xs' : 'h-9 px-3.5 text-[13px]';
    return (
        <div
            className={`inline-flex items-center ${wrapH} p-1 gap-0.5 rounded-[10px] bg-surface border border-border ${className}`}
            role="tablist"
        >
            {options.map(opt => {
                const active = opt.value === value;
                return (
                    <button
                        key={opt.value}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => onChange(opt.value)}
                        className={`inline-flex items-center justify-center ${segH} rounded-[7px] whitespace-nowrap transition-colors cursor-pointer ${
                            active
                                ? 'bg-primary text-on-color font-semibold'
                                : 'text-fg-muted font-medium hover:text-fg'
                        }`}
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
        })
    ).isRequired,
    value: PropTypes.string,
    onChange: PropTypes.func.isRequired,
    size: PropTypes.oneOf(['sm', 'md']),
    className: PropTypes.string,
};

export default SegmentedControl;
