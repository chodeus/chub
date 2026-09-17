import React from 'react';
import PropTypes from 'prop-types';

/** Shaped loading placeholder; prefer <Spinner /> for transient in-button actions. */
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
