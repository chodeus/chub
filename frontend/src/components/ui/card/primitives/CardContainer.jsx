import React, { useCallback } from 'react';
import PropTypes from 'prop-types';

/** Base card wrapper; `clickable` adds button semantics, Enter/Space and the pressed state. */
export const CardContainer = React.memo(
    ({
        children,
        hoverable = false,
        clickable = false,
        onClick,
        selected = false,
        className = '',
        'aria-label': ariaLabel,
        ...htmlProps
    }) => {
        // Handle click
        const handleClick = useCallback(
            event => {
                if (clickable && onClick) {
                    onClick(event);
                }
            },
            [clickable, onClick]
        );

        // Handle keyboard interaction
        const handleKeyDown = useCallback(
            event => {
                if (!clickable || !onClick) return;

                // Enter and Space should trigger click
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    handleClick(event);
                }
            },
            [clickable, onClick, handleClick]
        );

        // Build utility classes from test-ui utility system
        const cardClasses = [
            // Base structure (layout.css)
            'flex flex-col',

            // Surface styling (colors.css, borders.css)
            'bg-surface border border-border-light rounded-lg',

            // Overflow (layout.css)
            'overflow-hidden',

            // Transitions (animations.css)
            'transition-colors',

            // Hoverable state — subtle border shift, no shadow (flat RoomSketch feel)
            hoverable && 'hover:border-border',

            // Clickable state (interactions.css)
            clickable && 'cursor-pointer',

            // Selected state (borders.css, effects.css)
            selected && 'border-primary',

            // Additional classes
            className,
        ]
            .filter(Boolean)
            .join(' ');

        // Use article for semantic HTML
        const Component = clickable ? 'article' : 'div';

        return (
            <Component
                className={cardClasses}
                onClick={handleClick}
                onKeyDown={handleKeyDown}
                tabIndex={clickable ? 0 : undefined}
                role={clickable ? 'button' : undefined}
                aria-label={clickable ? ariaLabel : undefined}
                aria-pressed={clickable && selected ? 'true' : undefined}
                {...htmlProps}
            >
                {children}
            </Component>
        );
    }
);

CardContainer.displayName = 'CardContainer';

CardContainer.propTypes = {
    children: PropTypes.node.isRequired,
    hoverable: PropTypes.bool,
    clickable: PropTypes.bool,
    onClick: PropTypes.func,
    selected: PropTypes.bool,
    className: PropTypes.string,
    'aria-label': PropTypes.string,
};
