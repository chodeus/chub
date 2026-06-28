import React, { useCallback, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useSearchCoordinator, SEARCH_STATUS } from '../contexts/SearchCoordinatorContext.jsx';
import { useTheme } from '../contexts/ThemeContext.jsx';
import { useUIState } from '../contexts/UIStateContext.jsx';
import useSearchPageDetection from '../hooks/useSearchPageDetection.js';
import { useRecentSearches } from '../hooks/useRecentSearches.js';
import SearchInterface from './Search/SearchInterface.jsx';
import { HamburgerButton } from './ui/index.js';

// Mirrors the map in useDocumentTitle so the in-app header shows the same
// page name that the browser tab and breadcrumb already use. Keep them in
// sync — adding a route here without there means an empty header title.
const ROUTE_TITLES = {
    '/login': 'Sign in',
    '/dashboard': 'Dashboard',
    '/media/search': 'Library Search',
    '/media/manage': 'Library',
    '/media/statistics': 'Statistics',
    '/media/labelarr': 'Label Sync',
    '/poster/search/assets': 'Assets',
    '/poster/search/gdrive': 'GDrive',
    '/poster/cleanarr': 'Poster Cleanarr',
    '/poster/border-replacerr': 'Border Replacerr',
    '/poster/unmatched': 'Unmatched Assets',
    '/poster/statistics': 'Poster Stats',
    '/settings': 'Settings',
    '/settings/general': 'General',
    '/settings/modules': 'Modules',
    '/settings/instances': 'Instances',
    '/settings/schedule': 'Schedule',
    '/settings/jobs': 'Jobs',
    '/settings/notifications': 'Notifications',
    '/settings/webhooks': 'Webhooks',
    '/settings/system': 'System',
    '/logs': 'Logs',
};

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
    const { mobileMenuOpen, toggleMobileMenu, isMobile } = useUIState();
    const { pathname } = useLocation();
    const pageTitle = ROUTE_TITLES[pathname] || '';

    // Context-aware header detection
    const { isSearchPage, searchPageType, searchSubtype } = useSearchPageDetection();
    const { getSearchState } = useSearchCoordinator();
    const { recentSearches, addSearch } = useRecentSearches();

    // Watch the coordinator's status for the active search type and record a
    // recent search whenever a search "commits" — i.e. transitions out of
    // SEARCHING with a non-empty term. This fires after the coordinator's own
    // debounce settles, so we don't pollute history with mid-typing
    // intermediates, and covers both real-handler pages (MediaSearchPage)
    // and noop-handler pages (PosterAssetsSearchPage). Backspace-to-empty
    // goes SEARCHING → IDLE with term="" and is excluded by the term guard.
    //
    // The ref also tracks `type` so that cross-page navigation (e.g.
    // /media/search SEARCHING → /poster/search/assets IDLE) doesn't look like
    // a commit and accidentally record the posters page's leftover term.
    const activeState = searchPageType
        ? getSearchState(searchPageType)
        : { status: SEARCH_STATUS.IDLE, term: '' };
    const prevRef = useRef({ status: activeState.status, type: searchPageType });
    useEffect(() => {
        const prev = prevRef.current;
        if (
            prev.type === searchPageType &&
            prev.status === SEARCH_STATUS.SEARCHING &&
            activeState.status !== SEARCH_STATUS.SEARCHING &&
            activeState.term?.trim()
        ) {
            addSearch(activeState.term.trim());
        }
        prevRef.current = { status: activeState.status, type: searchPageType };
    }, [activeState.status, activeState.term, searchPageType, addSearch]);

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

    // Desktop folds branding into the sidebar, page titles into each page, and
    // search into in-page fields — so the top header is mobile-only now.
    if (!isMobile) return null;

    return (
        <header
            className={`shrink-0 h-14 bg-header-bg z-sticky ${isSearchPage ? 'search-page' : 'non-search-page'}`}
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
                        {/* Desktop branding now lives in the sidebar; keep the
                            banner element for mobile only (mobile shows the small
                            logo below, desktop shows nothing here). */}
                        <img
                            src="/img/chub-banner.png"
                            alt="CHUB — Media Manager"
                            className="hidden h-16 w-auto mt-3"
                            height="64"
                        />
                        <img
                            src="/img/chub-logo.png"
                            alt="CHUB"
                            className="md:hidden h-9 w-9"
                            width="36"
                            height="36"
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
                            suggestions={recentSearches}
                        />
                    </div>
                ) : (
                    /* Non-Search Page - show current page title so the wide empty
                       slot between hamburger and theme toggle has context */
                    <div className="flex-1 min-w-0 flex items-center justify-center md:justify-start">
                        {pageTitle && (
                            <h1 className="text-on-color font-semibold text-base md:text-lg truncate">
                                {pageTitle}
                            </h1>
                        )}
                    </div>
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
                        <span className="material-symbols-outlined" aria-hidden="true">
                            {getThemeIconName()}
                        </span>
                        <span className="max-sm:hidden">{getThemeDisplayText()}</span>
                    </button>
                </div>
            </div>
        </header>
    );
});

LayoutHeader.displayName = 'LayoutHeader';

export default LayoutHeader;
