import React from 'react';
import PropTypes from 'prop-types';

/** Card footer; `align` maps to the layout utility classes. */
export const CardFooter = React.memo(({ children, align = 'right', className = '' }) => {
    // Map alignment prop to utility classes (layout.css)
    const alignClasses = {
        left: 'justify-start',
        center: 'justify-center',
        right: 'justify-end',
        'space-between': 'justify-between',
    };

    return (
        <div
            className={`flex flex-wrap items-center gap-3 p-3 sm:p-4 sm:px-5 border-t border-default ${alignClasses[align]} ${className}`}
        >
            {children}
        </div>
    );
});

CardFooter.displayName = 'CardFooter';

CardFooter.propTypes = {
    children: PropTypes.node.isRequired,
    align: PropTypes.oneOf(['left', 'center', 'right', 'space-between']),
    className: PropTypes.string,
};
