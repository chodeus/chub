import React from 'react';
import PropTypes from 'prop-types';

/** Material Symbol for an error type: error → build, warning, info. */
export const ErrorIcon = ({ type = 'error', size = 'lg' }) => {
    const iconMap = {
        error: 'build',
        warning: 'warning',
        info: 'info',
    };

    const sizeClassMap = {
        sm: 'text-xl',
        md: 'text-2xl',
        lg: 'text-4xl',
    };

    const colorClassMap = {
        error: 'text-error',
        warning: 'text-warning',
        info: 'text-info',
    };

    if (size === 'lg') {
        return (
            <div className="text-center mb-8">
                <div
                    className={`material-symbols-outlined ${sizeClassMap[size]} mb-3 block ${colorClassMap[type]}`}
                    aria-hidden="true"
                >
                    {iconMap[type]}
                </div>
            </div>
        );
    }

    return (
        <span
            className={`material-symbols-outlined ${sizeClassMap[size]} shrink-0 mt-1 ${colorClassMap[type]}`}
            aria-hidden="true"
        >
            {iconMap[type]}
        </span>
    );
};

ErrorIcon.propTypes = {
    type: PropTypes.oneOf(['error', 'warning', 'info']),
    size: PropTypes.oneOf(['sm', 'md', 'lg']),
};
