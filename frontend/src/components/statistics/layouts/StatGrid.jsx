import React from 'react';
import PropTypes from 'prop-types';

/**
 * StatGrid - Grid layout for statistics cards
 *
 * Responsive grid that adapts from 1 column on mobile to
 * specified column count on desktop.
 *
 * Responsive Behavior:
 * - Mobile (default): auto-fit from 10rem, so 2+ columns once the viewport allows
 * - Tablet (md): min(columns, 2) columns
 * - Desktop (lg): specified columns
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children - StatCard components
 * @param {number} [props.columns=3] - Number of columns on desktop
 * @param {string} [props.gap="4"] - Gap size: "2", "3", "4", "6"
 * @param {string} [props.className=""] - Additional CSS classes
 * @returns {JSX.Element}
 *
 * @example
 * <StatGrid columns={3}>
 *   <StatCard label="Users" value={1234} />
 *   <StatCard label="Revenue" value={42000} />
 *   <StatCard label="Orders" value={567} />
 * </StatGrid>
 */
export const StatGrid = React.memo(({ children, columns = 3, gap = '4', className = '' }) => {
    if (!children) return null;

    const gapClasses = {
        2: 'gap-2',
        3: 'gap-3',
        4: 'gap-4',
        6: 'gap-6',
    };

    // Spelled out, not interpolated: Tailwind scans source text, so a built class
    // name only survives if some other file happens to write it literally.
    const mdColsClasses = { 1: 'md:grid-cols-1', 2: 'md:grid-cols-2' };
    const lgColsClasses = {
        1: 'lg:grid-cols-1',
        2: 'lg:grid-cols-2',
        3: 'lg:grid-cols-3',
        4: 'lg:grid-cols-4',
        5: 'lg:grid-cols-5',
        6: 'lg:grid-cols-6',
    };

    // Mobile uses auto-fit so 3- or 5-card grids don't produce orphan rows;
    // tablet pins to a 2-up grid for readability; desktop honours the requested
    // column count.
    const gridClasses = [
        'grid',
        'grid-cols-auto-fit-xs',
        mdColsClasses[Math.min(columns, 2)] || mdColsClasses[2],
        lgColsClasses[columns] || lgColsClasses[3],
        gapClasses[gap] || gapClasses['4'],
        className,
    ]
        .filter(Boolean)
        .join(' ');

    return <div className={gridClasses}>{children}</div>;
});

StatGrid.displayName = 'StatGrid';

StatGrid.propTypes = {
    children: PropTypes.node,
    columns: PropTypes.number,
    gap: PropTypes.oneOf(['2', '3', '4', '6']),
    className: PropTypes.string,
};
