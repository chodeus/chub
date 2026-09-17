import React from 'react';
import PropTypes from 'prop-types';

/** StatCards in a horizontal row; `wrap={false}` scrolls instead of wrapping. */
export const StatInline = React.memo(({ children, gap = '4', wrap = true, className = '' }) => {
    if (!children) return null;

    const gapClasses = {
        2: 'gap-2',
        3: 'gap-3',
        4: 'gap-4',
        6: 'gap-6',
    };

    const inlineClasses = [
        'flex',
        'flex-row',
        wrap ? 'flex-wrap' : 'overflow-x-auto',
        gapClasses[gap] || gapClasses['4'],
        className,
    ]
        .filter(Boolean)
        .join(' ');

    return <div className={inlineClasses}>{children}</div>;
});

StatInline.displayName = 'StatInline';

StatInline.propTypes = {
    children: PropTypes.node,
    gap: PropTypes.oneOf(['2', '3', '4', '6']),
    wrap: PropTypes.bool,
    className: PropTypes.string,
};
