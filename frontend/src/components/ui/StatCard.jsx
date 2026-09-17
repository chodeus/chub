import React from 'react';
import PropTypes from 'prop-types';
import { Card } from './card/Card';
import { StatIcon, StatLabel, StatValue, StatChange } from '../statistics/primitives';

/** Stat card composing Card with the stat primitives.
 *  `change.inverse` flips the up/down colouring, for metrics where down is good. */
export const StatCard = React.memo(
    ({
        label,
        value,
        icon,
        subtext,
        change,
        variant = 'standard',
        valueColor = '',
        valueFormat,
        badgeColor,
        className = '',
    }) => {
        return (
            <Card variant={variant} className={className}>
                <Card.Body>
                    <div className="flex flex-col gap-2 min-w-0">
                        {icon && badgeColor ? (
                            <div
                                className={`badge-bubble badge-bubble--${badgeColor} rounded-full w-14 h-14 text-3xl`}
                            >
                                <StatIcon icon={icon} size="2xl" />
                            </div>
                        ) : (
                            icon && <StatIcon icon={icon} />
                        )}
                        <StatLabel>{label}</StatLabel>
                        <StatValue color={valueColor} format={valueFormat}>
                            {value}
                        </StatValue>
                        {subtext && <StatLabel size="xs">{subtext}</StatLabel>}
                        {change && (
                            <StatChange
                                value={change.value}
                                direction={change.direction}
                                inverse={change.inverse}
                            />
                        )}
                    </div>
                </Card.Body>
            </Card>
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
    variant: PropTypes.oneOf(['standard', 'compact', 'bordered', 'minimal']),
    valueColor: PropTypes.oneOf(['', 'primary', 'success', 'warning', 'error']),
    valueFormat: PropTypes.func,
    badgeColor: PropTypes.oneOf([1, 2, 3, 4, 5, '1', '2', '3', '4', '5']),
    className: PropTypes.string,
};
