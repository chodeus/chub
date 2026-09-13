import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';

/** Toolbar context: mobile breakpoint, overflow menu state, and section overflow calculation. */
const ToolBarContext = createContext(null);

const MIN_BUTTON_WIDTH = 72;
const MORE_BUTTON_WIDTH = 64;
const SEPARATOR_MARGIN = 4;
const SEPARATOR_WIDTH = 2 * SEPARATOR_MARGIN + 1;

// Matches Separator.displayName; importing Separator here would be a circular import.
const isSeparator = child => child.type?.displayName === 'ToolBar.Separator';

// Prop-less children (spacers) are laid out like separators and never overflow.
const isButton = child => !isSeparator(child) && Object.keys(child.props).length > 0;

/** Splits a section's children into visible elements and overflowed button props. */
const calculateSectionOverflow = (children, sectionWidth, collapseButtons) => {
    // A 0 width means the section hasn't been measured yet.
    if (!collapseButtons || !sectionWidth) {
        const childArray = React.Children.toArray(children);
        return {
            visibleButtons: childArray,
            overflowItems: [],
            buttonCount: childArray.filter(child => React.isValidElement(child) && isButton(child))
                .length,
        };
    }

    let buttonCount = 0;
    let separatorCount = 0;
    const validChildren = [];

    React.Children.forEach(children, child => {
        if (!React.isValidElement(child)) return;
        if (isButton(child)) {
            buttonCount++;
        } else {
            separatorCount++;
        }
        validChildren.push(child);
    });

    const buttonsWidth = buttonCount * MIN_BUTTON_WIDTH;
    const separatorsWidth = separatorCount * SEPARATOR_WIDTH;
    const totalWidth = buttonsWidth + separatorsWidth;

    if (totalWidth <= sectionWidth) {
        return {
            visibleButtons: validChildren,
            overflowItems: [],
            buttonCount: buttonCount,
        };
    }

    const availableWidth = sectionWidth - separatorsWidth - MORE_BUTTON_WIDTH;
    const maxButtons = Math.max(Math.floor(availableWidth / MIN_BUTTON_WIDTH), 1);

    // Exactly one button would overflow: show every button instead, dropping separators and spacers.
    if (buttonCount - 1 === maxButtons) {
        return {
            visibleButtons: validChildren.filter(isButton),
            overflowItems: [],
            buttonCount: buttonCount,
        };
    }

    const buttons = [];
    const overflowItems = [];
    let actualButtons = 0;

    validChildren.forEach(child => {
        if (actualButtons < maxButtons) {
            buttons.push(child);
            if (isButton(child)) {
                actualButtons++;
            }
        } else if (isButton(child)) {
            overflowItems.push(child.props);
        }
    });

    return {
        visibleButtons: buttons,
        overflowItems: overflowItems,
        buttonCount: buttonCount,
    };
};

/**
 * useToolBar - Hook to consume ToolBar context
 *
 * @throws {Error} If used outside ToolBar provider
 * @returns {Object} Context value with responsive state and methods
 */
export const useToolBar = () => {
    const context = useContext(ToolBarContext);
    if (!context) {
        throw new Error('ToolBar subcomponents must be used within a ToolBar parent');
    }
    return context;
};

/**
 * ToolBarProvider - Context provider implementation
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children - Child components
 * @param {number} props.mobileBreakpoint - Mobile breakpoint in pixels
 */
export const ToolBarProvider = ({ children, mobileBreakpoint }) => {
    const [isMobile, setIsMobile] = useState(
        () => (typeof window !== 'undefined' ? window.innerWidth : 1024) < mobileBreakpoint
    );
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

    const toggleMobileMenu = useCallback(() => {
        setMobileMenuOpen(prev => !prev);
    }, []);

    const closeMobileMenu = useCallback(() => {
        setMobileMenuOpen(false);
    }, []);

    useEffect(() => {
        const handleResize = () => {
            setIsMobile(window.innerWidth < mobileBreakpoint);
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [mobileBreakpoint]);

    const contextValue = useMemo(
        () => ({
            isMobile,
            mobileMenuOpen,
            toggleMobileMenu,
            closeMobileMenu,
            calculateSectionOverflow,
        }),
        [isMobile, mobileMenuOpen, toggleMobileMenu, closeMobileMenu]
    );

    return <ToolBarContext.Provider value={contextValue}>{children}</ToolBarContext.Provider>;
};

ToolBarProvider.propTypes = {
    children: PropTypes.node.isRequired,
    mobileBreakpoint: PropTypes.number.isRequired,
};

export default ToolBarContext;
