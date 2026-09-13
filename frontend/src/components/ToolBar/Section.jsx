import React, { useMemo, useRef, useState, useLayoutEffect } from 'react';
import PropTypes from 'prop-types';
import Button from './Button.jsx';
import Dropdown from '../ui/Dropdown.jsx';
import Menu from '../ui/Menu.jsx';
import MenuItem from '../ui/MenuItem.jsx';
import { useToolBar } from './ToolBarContext.jsx';

/**
 * Responsive toolbar section component
 *
 * Uses ToolBarContext for overflow calculation instead of internal logic.
 *
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Toolbar buttons and separators
 * @param {string} [props.alignContent='left'] - Content alignment ('left', 'center', 'right')
 * @param {boolean} [props.collapseButtons=true] - Enable button collapse/overflow
 */
const Section = ({ children, alignContent = 'left', collapseButtons = true }) => {
    const sectionRef = useRef(null);
    const moreButtonRef = useRef(null);
    const [sectionWidth, setSectionWidth] = useState(0);
    const [isMenuOpen, setIsMenuOpen] = useState(false);

    // Get context for overflow calculation
    const { calculateSectionOverflow } = useToolBar();

    const handleMenuToggle = () => {
        setIsMenuOpen(!isMenuOpen);
    };

    const handleMenuClose = () => {
        setIsMenuOpen(false);
    };

    // Measure section width
    useLayoutEffect(() => {
        const section = sectionRef.current;
        if (!section) return undefined;

        setSectionWidth(section.offsetWidth);
        if (typeof ResizeObserver === 'undefined') return undefined;

        const observer = new ResizeObserver(() => setSectionWidth(section.offsetWidth));
        observer.observe(section);
        return () => observer.disconnect();
    }, []);

    // Force recalculation when children change
    useLayoutEffect(() => {
        if (sectionRef.current) {
            setSectionWidth(sectionRef.current.offsetWidth);
        }
    }, [children]);

    const { visibleButtons, overflowItems, buttonCount } = useMemo(() => {
        return calculateSectionOverflow(children, sectionWidth, collapseButtons);
    }, [calculateSectionOverflow, children, sectionWidth, collapseButtons]);

    const getJustifyClass = () => {
        switch (alignContent) {
            case 'left':
                return 'justify-start flex-1';
            case 'center':
                return 'justify-center flex-1';
            case 'right':
                return 'justify-end';
            default:
                return 'justify-start flex-1';
        }
    };

    const sectionClassName = ['flex items-center gap-1 min-w-0 overflow-hidden', getJustifyClass()]
        .filter(Boolean)
        .join(' ');

    return (
        <div
            ref={sectionRef}
            className={sectionClassName}
            style={{ flexGrow: alignContent === 'right' ? 0 : buttonCount }}
        >
            <div
                className={`flex items-center gap-1 min-w-0 overflow-hidden ${alignContent === 'right' ? '' : 'flex-1'}`}
            >
                {visibleButtons}
                {overflowItems.length > 0 && (
                    <>
                        <Button
                            ref={moreButtonRef}
                            label={`More (${overflowItems.length})`}
                            iconName="more_horiz"
                            onPress={handleMenuToggle}
                        />
                        <Dropdown
                            isOpen={isMenuOpen}
                            onClose={handleMenuClose}
                            anchorRef={moreButtonRef}
                            placement="bottom-right"
                            className="max-w-dropdown"
                        >
                            <Menu ariaLabel="More actions">
                                {overflowItems.map((item, index) => (
                                    <MenuItem
                                        key={`overflow-${index}`}
                                        label={item.label}
                                        iconName={item.iconName}
                                        onPress={item.onPress}
                                        isDisabled={item.isDisabled}
                                        onClose={handleMenuClose}
                                    />
                                ))}
                            </Menu>
                        </Dropdown>
                    </>
                )}
            </div>
        </div>
    );
};

Section.propTypes = {
    children: PropTypes.node.isRequired,
    alignContent: PropTypes.oneOf(['left', 'center', 'right']),
    collapseButtons: PropTypes.bool,
};

export default Section;
