import React from 'react';
import PropTypes from 'prop-types';

/** Row or column of buttons sharing orientation and spacing. */
export const ButtonGroup = React.memo(
    ({ children, orientation = 'horizontal', spacing = 'medium', className = '' }) => {
        // Build class names
        const groupClasses = [
            'btn-group',
            `btn-group-${orientation}`,
            `btn-group-spacing-${spacing}`,
            className,
        ]
            .filter(Boolean)
            .join(' ');

        return (
            <div className={groupClasses} role="group">
                {children}
            </div>
        );
    }
);

ButtonGroup.displayName = 'ButtonGroup';

ButtonGroup.propTypes = {
    children: PropTypes.node.isRequired,
    orientation: PropTypes.oneOf(['horizontal', 'vertical']),
    spacing: PropTypes.oneOf(['small', 'medium', 'large']),
    className: PropTypes.string,
};
