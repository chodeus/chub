import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSearchCoordinator } from '../contexts/SearchCoordinatorContext.jsx';
import { useTheme } from '../contexts/ThemeContext.jsx';
import { useUIState } from '../contexts/UIStateContext.jsx';
import useSearchPageDetection from '../hooks/useSearchPageDetection.js';
import { useRecentSearches } from '../hooks/useRecentSearches.js';
import SearchInterface from './Search/SearchInterface.jsx';
import { HamburgerButton } from './ui/index.js';

/**
 * LayoutHeader component for CHUB application - Phase 4D Context-Aware
 *
 * Context-aware header that adapts interface based on current page type:
 *
 * Search Pages (/media/search, /posters/search/*):
 * - Logo + Hamburger menu
 * - Search Input Field with debounced input (300ms)
 * - Smart Responsive Toolbar placeholder
 * - Search State Indicator
 *
 * Non-Search Pages:
 * - Logo + Hamburger menu only
 * - Clean, minimal header
 * - Theme toggle (temporary for testing)
 *
 * Features:
 * - CHUB logo from favicon-32x32.png
 * - Animated hamburger menu with SVG
 * - Route-based interface switching
 * - Mobile-first responsive design (375px+)
 * - Touch-optimized buttons (44px minimum)
 * - Uses design tokens for styling
 */
const LayoutHeader = React.memo(() => {
    const { toggleTheme, isDarkTheme, isLightTheme, isSystemTheme, actualTheme } = useTheme();
    const { mobileMenuOpen, toggleMobileMenu } = useUIState();

    // Context-aware header detection
    const { isSearchPage, searchPageType, searchSubtype } = useSearchPageDetection();
    const { search } = useSearchCoordinator();
    const { recentSearches, addSearch } = useRecentSearches();

    /**
     * Handle theme toggle click
     */
    const handleThemeToggle = useCallback(() => {
        toggleTheme();
    }, [toggleTheme]);

    /**
     * Handle hamburger menu click
     */
    const handleHamburgerClick = useCallback(() => {
        toggleMobileMenu();
    }, [toggleMobileMenu]);

    /**
     * Handle search action from SearchInterface - triggers the registered search handler
     */
    const handleSearch = useCallback(
        searchTerm => {
            if (searchPageType) {
                search(searchPageType, searchTerm, { immediate: true });
                if (searchTerm && searchTerm.trim()) {
                    addSearch(searchTerm.trim());
                }
            }
        },
        [searchPageType, search, addSearch]
    );

    /**
     * Get theme display text for button
     */
    const getThemeDisplayText = () => {
        if (isSystemTheme) {
            return `System (${actualTheme})`;
        }
        return actualTheme.charAt(0).toUpperCase() + actualTheme.slice(1);
    };

    /**
     * Get theme icon name for button
     */
    const getThemeIconName = () => {
        if (isDarkTheme) {
            return 'light_mode';
        } else if (isLightTheme) {
            return 'dark_mode';
        } else {
            return 'settings_suggest';
        }
    };

    return (
        <header
            className={`shrink-0 h-20 bg-header-bg z-sticky min-h-header ${isSearchPage ? 'search-page' : 'non-search-page'}`}
            role="banner"
        >
            <div
                className={`flex items-center justify-between h-full px-4 max-w-full ${isSearchPage ? 'gap-4' : 'gap-3'}`}
            >
                {/* Brand/Logo Section with Hamburger */}
                <div className="flex items-center gap-3 shrink-0">
                    {/* CHUB Logo - Clickable Link to Home */}
                    <Link
                        to="/"
                        className="touch-target flex items-center no-underline cursor-pointer transition-opacity hover:opacity-80 focus:outline-focus"
                        aria-label="CHUB — Media Manager"
                    >
                        <img
                            src="/img/chub-banner.png"
                            alt="CHUB — Media Manager"
                            className="max-md:hidden h-16 w-auto mt-3"
                            height="64"
                        />
                        <img
                            src="/img/chub-logo.png"
                            alt="CHUB"
                            className="md:hidden h-12 w-12 mt-2"
                            width="48"
                            height="48"
                        />
                    </Link>

                    {/* Hamburger Menu Button */}
                    <HamburgerButton
                        isOpen={mobileMenuOpen}
                        onClick={handleHamburgerClick}
                        ariaLabel="Main Menu"
                    />
                </div>

                {/* Context-Aware Content Area */}
                {isSearchPage ? (
                    /* Search Page Interface */
                    <div className="flex-1 max-w-500 mx-auto flex items-center justify-center">
                        <SearchInterface
                            searchPageType={searchPageType}
                            searchSubtype={searchSubtype}
                            onSearch={handleSearch}
                            suggestions={recentSearches}
                        />
                    </div>
                ) : (
                    /* Non-Search Page - Clean Spacer */
                    <div className="flex-1">{/* Clean minimal header for non-search pages */}</div>
                )}

                {/* Actions Section - Always show theme toggle */}
                <div className="flex items-center gap-3 shrink-0">
                    {/* Theme Toggle */}
                    <button
                        className="flex items-center gap-2 px-3 py-2 bg-sidebar-hover border border-transparent rounded-lg text-on-color text-sm font-medium cursor-pointer transition-fast touch-target whitespace-nowrap hover:opacity-80 focus:outline-focus focus:outline-offset-2"
                        onClick={handleThemeToggle}
                        type="button"
                        aria-label={`Switch to ${isDarkTheme ? 'light' : 'dark'} theme`}
                        title={`Current: ${getThemeDisplayText()}. Click to toggle theme.`}
                    >
                        <span
                            className="theme-toggle-icon material-symbols-outlined"
                            aria-hidden="true"
                        >
                            {getThemeIconName()}
                        </span>
                        <span className="theme-toggle-text max-sm:hidden">
                            {getThemeDisplayText()}
                        </span>
                    </button>
                </div>
            </div>
        </header>
    );
});

LayoutHeader.displayName = 'LayoutHeader';

export default LayoutHeader;
