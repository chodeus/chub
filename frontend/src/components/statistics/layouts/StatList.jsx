import React from 'react';
import PropTypes from 'prop-types';

/** StatCards stacked vertically with consistent spacing. */
export const StatList = React.memo(({ children, gap = '3', className = '' }) => {
    if (!children) return null;

    const gapClasses = {
        2: 'gap-2',
        3: 'gap-3',
        4: 'gap-4',
    };

    const listClasses = ['flex', 'flex-col', gapClasses[gap] || gapClasses['3'], className]
        .filter(Boolean)
        .join(' ');

    return <div className={listClasses}>{children}</div>;
});

StatList.displayName = 'StatList';

StatList.propTypes = {
    children: PropTypes.node,
    gap: PropTypes.oneOf(['2', '3', '4']),
    className: PropTypes.string,
};
