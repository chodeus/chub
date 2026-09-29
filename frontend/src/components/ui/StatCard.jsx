import React from 'react';
import PropTypes from 'prop-types';
import { StatIcon, StatChange } from '../statistics/primitives';

const VALUE_TONES = {
    success: 'text-success',
    warning: 'text-warning',
    error: 'text-error',
    accent: 'text-accent',
};

/** Summary tile: mono label, large mono value, and a subtext row that is always
 *  reserved so sibling tiles line up. `change.inverse` flips the trend colouring. */
export const StatCard = React.memo(
    ({ label, value, icon, subtext, change, valueColor = '', valueFormat, className = '' }) => {
        const display = valueFormat
            ? valueFormat(value)
            : typeof value === 'number'
              ? value.toLocaleString()
              : value;
        return (
            <div
                className={`p-5 rounded-xl bg-surface border border-border flex flex-col min-w-0 shadow-[0_2px_16px_-8px_rgba(0,0,0,0.6)] ${className}`}
            >
                {icon && <StatIcon icon={icon} size="2xl" className="mb-2" />}
                <p className="eyebrow mt-0 mb-4">{label}</p>
                <p
                    className={`font-mono text-stat leading-none font-semibold mt-2 mb-4 ${VALUE_TONES[valueColor] || 'text-fg'}`}
                >
                    {display}
                </p>
                <p className="text-meta text-fg-subtle mt-1.5 mb-4">{subtext || '\u00a0'}</p>
                {change && (
                    <StatChange
                        value={change.value}
                        direction={change.direction}
                        inverse={change.inverse}
                    />
                )}
            </div>
        );
    }
);

StatCard.displayName = 'StatCard';

StatCard.propTypes = {
    label: PropTypes.string.isRequired,
    value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    icon: PropTypes.oneOfType([PropTypes.string, PropTypes.node]),
    subtext: PropTypes.string,
    change: PropTypes.shape({
        value: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
        direction: PropTypes.oneOf(['up', 'down', 'neutral']),
        inverse: PropTypes.bool,
    }),
    // 'primary' is the default text colour, kept for existing callers.
    valueColor: PropTypes.oneOf(['', 'primary', 'success', 'warning', 'error', 'accent']),
    valueFormat: PropTypes.func,
    className: PropTypes.string,
};
