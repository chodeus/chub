import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';

/**
 * Theme context for managing dark/light theme state
 */

// Available theme options
export const THEMES = {
    LIGHT: 'light',
    DARK: 'dark',
    SYSTEM: 'system',
};

// Local storage key for theme preference
const THEME_STORAGE_KEY = 'chub-theme-preference';
const ACCENT_STORAGE_KEY = 'chub-accent-preference';

// Per theme: the brand fill, its text hover, and the ink that sits ON the fill. Light shades are
// darker so the accent reads as text on light surfaces; contrast.test.js holds them to 4.5:1.
export const ACCENTS = {
    violet: {
        label: 'Violet',
        dark: { brand: '#7c58f6', hover: '#a99eff', onBrand: '#ffffff' },
        light: { brand: '#463fbc', hover: '#3a339e', onBrand: '#ffffff' },
    },
    cyan: {
        label: 'Cyan',
        dark: { brand: '#53e8f0', hover: '#7af0f5', onBrand: '#110b28' },
        light: { brand: '#0c627a', hover: '#094c5e', onBrand: '#ffffff' },
    },
    azure: {
        label: 'Azure',
        dark: { brand: '#0b78d0', hover: '#47a9f6', onBrand: '#ffffff' },
        light: { brand: '#0b5b9f', hover: '#094d87', onBrand: '#ffffff' },
    },
    gold: {
        label: 'Gold',
        dark: { brand: '#ffc944', hover: '#ffd873', onBrand: '#110b28' },
        light: { brand: '#785400', hover: '#593f00', onBrand: '#ffffff' },
    },
};
const DEFAULT_ACCENT = 'violet';

const shadeKey = theme => (theme === THEMES.LIGHT ? 'light' : 'dark');

const getStoredAccent = () => {
    if (typeof window === 'undefined') return DEFAULT_ACCENT;
    try {
        const a = localStorage.getItem(ACCENT_STORAGE_KEY);
        return a && ACCENTS[a] ? a : DEFAULT_ACCENT;
    } catch {
        return DEFAULT_ACCENT;
    }
};

const storeAccent = accent => {
    if (typeof window === 'undefined') return;
    try {
        localStorage.setItem(ACCENT_STORAGE_KEY, accent);
    } catch (error) {
        console.warn('Failed to store accent preference in localStorage:', error);
    }
};

// Set the brand CSS variables inline on <html> so they win over the theme
// stylesheet (which defines the Violet defaults). The shared components read
// var(--primary) / var(--on-color-text), so this recolours the whole app.
const applyAccent = (accent, theme) => {
    if (typeof document === 'undefined') return;
    const shades = ACCENTS[accent] || ACCENTS[DEFAULT_ACCENT];
    const a = shades[shadeKey(theme)];
    const s = document.documentElement.style;
    s.setProperty('--primary', a.brand);
    s.setProperty('--primary-hover', a.hover);
    s.setProperty('--primary-text', a.onBrand);
    s.setProperty('--on-color-text', a.onBrand);
    // The sidebar and header stay dark in both themes, so they keep the dark shade.
    s.setProperty('--sidebar-accent', shades.dark.brand);
    s.setProperty('--sidebar-on-accent', shades.dark.onBrand);
};

// Create context
const ThemeContext = createContext();

/**
 * Custom hook to use theme context
 * @returns {Object} Theme context value with methods and state
 */
export const useTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) {
        throw new Error('useTheme must be used within a ThemeProvider');
    }
    return context;
};

/**
 * Get system theme preference
 * @returns {string} 'light' or 'dark'
 */
const getSystemTheme = () => {
    if (typeof window === 'undefined') return THEMES.DARK;

    return window.matchMedia('(prefers-color-scheme: dark)').matches ? THEMES.DARK : THEMES.LIGHT;
};

/**
 * Get stored theme preference or default
 * @returns {string} Theme preference
 */
const getStoredTheme = () => {
    if (typeof window === 'undefined') return null;

    try {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        // null, not SYSTEM, so callers can fall back to their own default.
        return stored && Object.values(THEMES).includes(stored) ? stored : null;
    } catch (error) {
        console.warn('Failed to read theme preference from localStorage:', error);
        return null;
    }
};

/**
 * Store theme preference
 * @param {string} theme - Theme to store
 */
const storeTheme = theme => {
    if (typeof window === 'undefined') return;

    try {
        localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (error) {
        console.warn('Failed to store theme preference in localStorage:', error);
    }
};

/**
 * Apply theme to document
 * @param {string} theme - Theme to apply ('light' or 'dark')
 */
const applyTheme = theme => {
    if (typeof document === 'undefined') return;

    // Remove existing theme attributes
    document.documentElement.removeAttribute('data-theme');
    document.body.classList.remove('theme-light', 'theme-dark');

    // Apply new theme
    document.documentElement.setAttribute('data-theme', theme);
    document.body.classList.add(`theme-${theme}`);

    // Update meta theme-color for mobile browsers
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
        const themeColor =
            theme === THEMES.DARK
                ? '#1a1a1a' // Dark theme color
                : '#ffffff'; // Light theme color
        metaThemeColor.setAttribute('content', themeColor);
    }
};

/**
 * Theme Provider component
 */
export const ThemeProvider = ({ children, defaultTheme = THEMES.SYSTEM }) => {
    // Lazy initialization reads localStorage / prefers-color-scheme once at mount.
    // Avoids a setState-in-effect on first render.
    const [themePreference, setThemePreference] = useState(() => getStoredTheme() ?? defaultTheme);
    const [systemTheme, setSystemTheme] = useState(() => getSystemTheme());
    const [actualTheme, setActualTheme] = useState(() => {
        const stored = getStoredTheme() ?? defaultTheme;
        return stored === THEMES.SYSTEM ? getSystemTheme() : stored;
    });
    const [accent, setAccentState] = useState(() => getStoredAccent());

    // Apply the brand accent to the document (external side-effect, no setState).
    useEffect(() => {
        applyAccent(accent, actualTheme);
    }, [accent, actualTheme]);

    // Each accent with the current theme's shades, so the picker's swatches match what applies.
    const accents = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(ACCENTS).map(([key, a]) => [
                    key,
                    { label: a.label, ...a[shadeKey(actualTheme)] },
                ])
            ),
        [actualTheme]
    );

    const setAccent = useCallback(next => {
        if (!ACCENTS[next]) return;
        setAccentState(next);
        storeAccent(next);
    }, []);

    /**
     * Apply the resolved theme to the document after mount. This is a pure
     * side-effect onto an external system (the DOM) — no setState.
     */
    useEffect(() => {
        applyTheme(actualTheme);
    }, [actualTheme]);

    /**
     * Listen for system theme changes
     */
    useEffect(() => {
        if (typeof window === 'undefined') return;

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        const handleSystemThemeChange = e => {
            const newSystemTheme = e.matches ? THEMES.DARK : THEMES.LIGHT;
            setSystemTheme(newSystemTheme);

            // If user prefers system theme, update actual theme.
            // applyTheme runs automatically via the actualTheme effect.
            if (themePreference === THEMES.SYSTEM) {
                setActualTheme(newSystemTheme);
            }
        };

        // Modern browsers
        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleSystemThemeChange);
            return () => mediaQuery.removeEventListener('change', handleSystemThemeChange);
        }
        // Older browsers
        else if (mediaQuery.addListener) {
            mediaQuery.addListener(handleSystemThemeChange);
            return () => mediaQuery.removeListener(handleSystemThemeChange);
        }
    }, [themePreference]);

    /**
     * Set theme preference
     * @param {string} theme - Theme to set
     */
    const setTheme = useCallback(
        theme => {
            if (!Object.values(THEMES).includes(theme)) {
                console.warn(`Invalid theme: ${theme}. Using system theme instead.`);
                theme = THEMES.SYSTEM;
            }

            setThemePreference(theme);
            storeTheme(theme);

            // Determine actual theme to apply. applyTheme runs via the
            // actualTheme effect — no manual call needed here.
            const themeToApply = theme === THEMES.SYSTEM ? systemTheme : theme;
            setActualTheme(themeToApply);
        },
        [systemTheme]
    );

    /**
     * Toggle between light and dark themes
     * If currently on system, goes to opposite of current system theme
     */
    const toggleTheme = useCallback(() => {
        if (themePreference === THEMES.SYSTEM) {
            // If on system, switch to opposite of current system theme
            setTheme(systemTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK);
        } else {
            // If on specific theme, toggle to opposite
            setTheme(themePreference === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK);
        }
    }, [themePreference, systemTheme, setTheme]);

    /**
     * Reset to system preference
     */
    const useSystemTheme = useCallback(() => {
        setTheme(THEMES.SYSTEM);
    }, [setTheme]);

    /**
     * Check if theme is dark
     */
    const isDarkTheme = actualTheme === THEMES.DARK;

    /**
     * Check if theme is light
     */
    const isLightTheme = actualTheme === THEMES.LIGHT;

    /**
     * Check if using system preference
     */
    const isSystemTheme = themePreference === THEMES.SYSTEM;

    const contextValue = {
        // Current state
        themePreference,
        actualTheme,
        systemTheme,

        // Boolean helpers
        isDarkTheme,
        isLightTheme,
        isSystemTheme,

        // Accent
        accent,
        setAccent,
        accents,

        // Actions
        setTheme,
        toggleTheme,
        useSystemTheme,

        // Theme constants
        themes: THEMES,
    };

    return <ThemeContext.Provider value={contextValue}>{children}</ThemeContext.Provider>;
};

ThemeProvider.propTypes = {
    children: PropTypes.node.isRequired,
    defaultTheme: PropTypes.oneOf(Object.values(THEMES)),
};

/**
 * Higher-order component to inject theme props
 * @param {React.Component} Component - Component to wrap
 * @returns {React.Component} Enhanced component with theme props
 */
export const withTheme = Component => {
    const WrappedComponent = props => {
        const theme = useTheme();
        return <Component {...props} theme={theme} />;
    };

    WrappedComponent.displayName = `withTheme(${Component.displayName || Component.name})`;

    return WrappedComponent;
};
