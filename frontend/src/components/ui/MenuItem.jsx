import React from 'react';
import PropTypes from 'prop-types';

/** Menu row with an optional icon; `onClose` dismisses the parent menu after the press. */
const MenuItem = ({
    label,
    iconName,
    onPress,
    isDisabled = false,
    onClose,
    className = '',
    ...otherProps
}) => {
    const handleClick = event => {
        event.preventDefault();
        if (!isDisabled && onPress) {
            onPress();
            if (onClose) {
                onClose(); // Close parent menu after action
            }
        }
    };

    const handleKeyDown = event => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleClick(event);
        }
    };

    const itemClassName = [
        'flex items-center gap-2 py-2 px-3 touch-target bg-transparent text-fg-muted border-none rounded-sm cursor-pointer text-sm w-full text-left whitespace-nowrap',
        'transition-colors focus:outline-none active:text-fg md:text-base',
        isDisabled
            ? 'text-fg-subtle cursor-not-allowed hover:text-fg-subtle focus:text-fg-subtle active:text-fg-subtle'
            : 'hover:bg-surface-hover focus:bg-surface-hover menu-item-focus',
        className,
    ]
        .filter(Boolean)
        .join(' ');

    return (
        <div
            className={itemClassName}
            role="menuitem"
            tabIndex={isDisabled ? -1 : 0}
            onClick={handleClick}
            onKeyDown={handleKeyDown}
            aria-disabled={isDisabled}
            {...otherProps}
        >
            {iconName && (
                <span
                    className="material-symbols-outlined flex-shrink-0 icon-md flex items-center justify-center"
                    aria-hidden="true"
                >
                    {iconName}
                </span>
            )}
            <span className="flex-1 min-w-0 text-ellipsis">{label}</span>
        </div>
    );
};

MenuItem.propTypes = {
    label: PropTypes.string.isRequired,
    iconName: PropTypes.string,
    onPress: PropTypes.func,
    isDisabled: PropTypes.bool,
    onClose: PropTypes.func,
    className: PropTypes.string,
};

export default MenuItem;
