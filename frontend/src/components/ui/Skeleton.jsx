import React from 'react';
import PropTypes from 'prop-types';

/**
 * Skeleton - Animated placeholder for loading content.
 *
 * Use in place of <Spinner /> when you can describe the shape of the content
 * that's about to appear (a row of cards, a table row, a paragraph). For
 * transient in-button actions, prefer <Spinner /> — skeletons aren't a
 * universal upgrade.
 *
 * @param {Object} props
 * @param {string|number} [props.width] - CSS width (e.g. "100%", "8rem", 200)
 * @param {string|number} [props.height] - CSS height (default "1rem")
 * @param {string} [props.rounded] - One of "none" | "sm" | "md" | "lg" | "full"
 * @param {string} [props.className] - Additional classes
 */
export const Skeleton = React.memo(
    ({ width = '100%', height = '1rem', rounded = 'md', className = '', ...rest }) => {
        const roundedClass = {
            none: '',
            sm: 'rounded-sm',
            md: 'rounded-md',
            lg: 'rounded-lg',
            full: 'rounded-full',
        }[rounded];

        const style = {
            width: typeof width === 'number' ? `${width}px` : width,
            height: typeof height === 'number' ? `${height}px` : height,
        };

        return (
            <div
                role="presentation"
                aria-hidden="true"
                className={`animate-pulse bg-surface-alt ${roundedClass} ${className}`.trim()}
                style={style}
                {...rest}
            />
        );
    }
);

Skeleton.displayName = 'Skeleton';

Skeleton.propTypes = {
    width: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    height: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    rounded: PropTypes.oneOf(['none', 'sm', 'md', 'lg', 'full']),
    className: PropTypes.string,
};

export default Skeleton;
