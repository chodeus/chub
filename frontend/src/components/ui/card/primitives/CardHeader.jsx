import React from 'react';
import PropTypes from 'prop-types';

/** Card header: title as an h3, optional subtitle and action slot. */
export const CardHeader = React.memo(
    ({ title, subtitle = null, action = null, className = '' }) => {
        return (
            <div
                className={`flex items-start justify-between gap-4 p-4 px-5 border-b border-default ${className}`}
            >
                <div className="flex-1 min-w-0">
                    {title && (
                        <h3 className="m-0 text-lg font-semibold text-fg leading-snug">{title}</h3>
                    )}
                    {subtitle && (
                        <p className="mt-1 m-0 text-sm text-fg-muted leading-normal">{subtitle}</p>
                    )}
                </div>
                {action && <div className="flex-none">{action}</div>}
            </div>
        );
    }
);

CardHeader.displayName = 'CardHeader';

CardHeader.propTypes = {
    title: PropTypes.string.isRequired,
    subtitle: PropTypes.string,
    action: PropTypes.node,
    className: PropTypes.string,
};
