import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import PropTypes from 'prop-types';

/** Global UI state: viewport, sidebar and mobile menu. */

// Breakpoint constants
const BREAKPOINTS = {
    MOBILE: 768,
    TABLET: 1024,
};

// Create context
const UIStateContext = createContext();

/**
 * Custom hook to use UI state context
 * @returns {Object} UI state context value with methods and state
 */
export const useUIState = () => {
    const context = useContext(UIStateContext);
    if (!context) {
        throw new Error('useUIState must be used within a UIStateProvider');
    }
    return context;
};

/**
 * Get current viewport size
 * @returns {Object} Viewport dimensions and breakpoint info
 */
const getViewportInfo = () => {
    if (typeof window === 'undefined') {
        return {
            width: 1024,
            height: 768,
            isMobile: false,
            isTablet: false,
            isDesktop: true,
        };
    }

    const width = window.innerWidth;
    const height = window.innerHeight;

    return {
        width,
        height,
        isMobile: width < BREAKPOINTS.MOBILE,
        isTablet: width >= BREAKPOINTS.MOBILE && width < BREAKPOINTS.TABLET,
        isDesktop: width >= BREAKPOINTS.TABLET,
    };
};

/** Provides viewport, sidebar and mobile-menu state; persists the sidebar to localStorage. */
export const UIStateProvider = ({
    children,
    defaultSidebarCollapsed = false,
    persistUIState = true,
}) => {
    const [viewport, setViewport] = useState(() => getViewportInfo());
    // Lazy-init from localStorage so we don't need a setState-in-effect bootstrap.
    const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
        if (!persistUIState || typeof window === 'undefined') return defaultSidebarCollapsed;
        try {
            const stored = localStorage.getItem('chub-ui-state');
            if (stored) {
                const parsedState = JSON.parse(stored);
                if (typeof parsedState.sidebarCollapsed === 'boolean') {
                    return parsedState.sidebarCollapsed;
                }
            }
        } catch (error) {
            console.warn('Failed to load UI state from localStorage:', error);
        }
        return defaultSidebarCollapsed;
    });
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

    /**
     * Persist UI state to localStorage
     */
    const persistState = useCallback(
        state => {
            if (!persistUIState || typeof window === 'undefined') return;

            try {
                const currentStored = localStorage.getItem('chub-ui-state');
                const currentState = currentStored ? JSON.parse(currentStored) : {};
                const newState = { ...currentState, ...state };
                localStorage.setItem('chub-ui-state', JSON.stringify(newState));
            } catch (error) {
                console.warn('Failed to persist UI state to localStorage:', error);
            }
        },
        [persistUIState]
    );

    /**
     * Handle viewport changes
     */
    useEffect(() => {
        if (typeof window === 'undefined') return;

        const handleResize = () => {
            const newViewport = getViewportInfo();
            setViewport(newViewport);

            // Auto-close mobile menu on desktop
            if (newViewport.isDesktop && mobileMenuOpen) {
                setMobileMenuOpen(false);
            }
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [mobileMenuOpen]);

    /**
     * Toggle sidebar collapsed state
     */
    const toggleSidebar = useCallback(() => {
        setSidebarCollapsed(prev => {
            const newState = !prev;
            persistState({ sidebarCollapsed: newState });
            return newState;
        });
    }, [persistState]);

    /**
     * Set sidebar collapsed state
     * @param {boolean} collapsed - Whether sidebar should be collapsed
     */
    const setSidebarCollapsedState = useCallback(
        collapsed => {
            setSidebarCollapsed(collapsed);
            persistState({ sidebarCollapsed: collapsed });
        },
        [persistState]
    );

    /**
     * Toggle mobile menu
     */
    const toggleMobileMenu = useCallback(() => {
        setMobileMenuOpen(prev => !prev);
    }, []);

    /**
     * Close mobile menu
     */
    const closeMobileMenu = useCallback(() => {
        setMobileMenuOpen(false);
    }, []);

    // Escape closes the mobile menu.
    useEffect(() => {
        const handleEscape = event => {
            if (event.key === 'Escape' && mobileMenuOpen) {
                closeMobileMenu();
            }
        };

        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [mobileMenuOpen, closeMobileMenu]);

    const contextValue = {
        // Viewport info
        viewport,

        // Sidebar state
        sidebarCollapsed,
        toggleSidebar,
        setSidebarCollapsed: setSidebarCollapsedState,

        // Mobile menu state
        mobileMenuOpen,
        toggleMobileMenu,
        closeMobileMenu,

        // Convenience boolean flags
        isMobile: viewport.isMobile,
        isTablet: viewport.isTablet,
        isDesktop: viewport.isDesktop,
    };

    return <UIStateContext.Provider value={contextValue}>{children}</UIStateContext.Provider>;
};

UIStateProvider.propTypes = {
    children: PropTypes.node.isRequired,
    defaultSidebarCollapsed: PropTypes.bool,
    persistUIState: PropTypes.bool,
};
