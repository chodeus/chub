import React from 'react';
import PropTypes from 'prop-types';

/** Material Symbols icon sized to the button scale; aria-hidden by default. */
export const ButtonIcon = React.memo(
    ({ icon, size = 'medium', className = '', 'aria-hidden': ariaHidden = true }) => {
        // Map size to text size utilities (Material Symbols uses font-size)
        // Redesigned scale with meaningful differentiation for accessibility
        const sizeClasses = {
            small: 'text-xl', // 1.25rem (20px) - Minimum for inline/compact contexts
            medium: 'text-2xl', // 1.5rem (24px) - Standard toolbar/button icons (Material Design)
            large: 'text-4xl', // 2.25rem (36px) - Prominent actions/headers
        };

        // Build class names using utility classes only
        const iconClasses = [
            'inline-flex', // Display: inline-flex for proper alignment
            'items-center', // Vertical center alignment
            'justify-center', // Horizontal center alignment
            sizeClasses[size], // Font size for icon
            className,
        ]
            .filter(Boolean)
            .join(' ');

        return (
            <span
                className={iconClasses}
                aria-hidden={ariaHidden}
                style={{ fontFamily: 'Material Symbols Outlined' }}
            >
                {icon}
            </span>
        );
    }
);

ButtonIcon.displayName = 'ButtonIcon';

ButtonIcon.propTypes = {
    icon: PropTypes.string.isRequired,
    size: PropTypes.oneOf(['small', 'medium', 'large']),
    className: PropTypes.string,
    'aria-hidden': PropTypes.bool,
};
