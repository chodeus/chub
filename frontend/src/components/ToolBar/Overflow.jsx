import React, { useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useToolBar } from './ToolBarContext.jsx';
import Button from './Button.jsx';
import Dropdown from '../ui/Dropdown.jsx';
import Menu from '../ui/Menu.jsx';
import MenuItem from '../ui/MenuItem.jsx';

/** Toggle + dropdown menu for the `overflowButtons` prop; renders nothing while it is `null` or empty. */
const Overflow = ({
    position = 'right',
    menuIcon = 'more_vert',
    overflowButtons = null,
    onItemClick,
}) => {
    const overflowButtonRef = useRef(null);
    const [isMenuOpen, setIsMenuOpen] = useState(false);

    const { mobileMenuOpen, toggleMobileMenu, closeMobileMenu, isMobile } = useToolBar();

    const buttons = overflowButtons || [];

    const handleMenuToggle = () => {
        if (isMobile) {
            toggleMobileMenu();
        } else {
            setIsMenuOpen(!isMenuOpen);
        }
    };

    const handleMenuClose = React.useCallback(() => {
        if (isMobile) {
            closeMobileMenu();
        } else {
            setIsMenuOpen(false);
        }
    }, [isMobile, closeMobileMenu]);

    // MenuItem calls onClose after onPress; Dropdown owns outside-click and Escape.
    const handleItemClick = (button, event) => {
        if (onItemClick) {
            onItemClick(button, event);
        } else if (button.onPress) {
            button.onPress(event);
        }
    };

    // Don't render if no overflow buttons
    if (buttons.length === 0) {
        return null;
    }

    const dropdownPlacement = position === 'left' ? 'bottom-left' : 'bottom-right';

    return (
        <>
            <Button
                ref={overflowButtonRef}
                label={isMobile ? 'Menu' : `More (${buttons.length})`}
                iconName={menuIcon}
                onPress={handleMenuToggle}
                aria-expanded={isMobile ? mobileMenuOpen : isMenuOpen}
                aria-haspopup="menu"
                aria-label={`Show ${buttons.length} more actions`}
            />
            <Dropdown
                isOpen={isMobile ? mobileMenuOpen : isMenuOpen}
                onClose={handleMenuClose}
                anchorRef={overflowButtonRef}
                placement={dropdownPlacement}
                className={isMobile ? 'w-full' : 'max-w-dropdown'}
            >
                <Menu ariaLabel="Overflow actions">
                    {buttons.map((button, index) => (
                        <MenuItem
                            key={button.key || `overflow-${index}`}
                            label={button.label}
                            iconName={button.iconName}
                            onPress={event => handleItemClick(button, event)}
                            isDisabled={button.isDisabled}
                            onClose={handleMenuClose}
                        />
                    ))}
                </Menu>
            </Dropdown>
        </>
    );
};

Overflow.propTypes = {
    position: PropTypes.oneOf(['left', 'right']),
    menuIcon: PropTypes.string,
    overflowButtons: PropTypes.arrayOf(
        PropTypes.shape({
            key: PropTypes.string,
            label: PropTypes.string.isRequired,
            iconName: PropTypes.string,
            onPress: PropTypes.func,
            isDisabled: PropTypes.bool,
        })
    ),
    onItemClick: PropTypes.func,
};

export default Overflow;
