import { act, render, renderHook } from '@testing-library/react';
import { ACCENTS, ThemeProvider, THEMES, useTheme } from './ThemeContext.jsx';

const THEME_KEY = 'chub-theme-preference';
const ACCENT_KEY = 'chub-accent-preference';

const renderWithTheme = props =>
    render(
        <ThemeProvider {...props}>
            <span>child</span>
        </ThemeProvider>
    );

const darkByDefault = ({ children }) => (
    <ThemeProvider defaultTheme={THEMES.DARK}>{children}</ThemeProvider>
);

const primary = () => document.documentElement.style.getPropertyValue('--primary');

describe('ThemeProvider', () => {
    beforeEach(() => {
        localStorage.clear();
        document.documentElement.removeAttribute('data-theme');
        document.documentElement.removeAttribute('style');
    });

    it("applies the stored accent's light shade in the light theme", () => {
        localStorage.setItem(THEME_KEY, THEMES.LIGHT);
        localStorage.setItem(ACCENT_KEY, 'gold');

        renderWithTheme({ defaultTheme: THEMES.DARK });

        expect(primary()).toBe(ACCENTS.gold.light.brand);
        // The sidebar and header stay dark, so they keep the dark shade.
        expect(document.documentElement.style.getPropertyValue('--sidebar-accent')).toBe(
            ACCENTS.gold.dark.brand
        );
    });

    it('re-applies the accent and the picker shades when the theme changes', () => {
        localStorage.setItem(ACCENT_KEY, 'gold');
        const { result } = renderHook(() => useTheme(), { wrapper: darkByDefault });
        expect(primary()).toBe(ACCENTS.gold.dark.brand);

        act(() => result.current.setTheme(THEMES.LIGHT));

        expect(primary()).toBe(ACCENTS.gold.light.brand);
        expect(result.current.accents.gold.brand).toBe(ACCENTS.gold.light.brand);
    });

    it('honours defaultTheme when nothing is stored', () => {
        renderWithTheme({ defaultTheme: THEMES.DARK });

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('prefers a stored preference over defaultTheme', () => {
        localStorage.setItem(THEME_KEY, THEMES.LIGHT);

        renderWithTheme({ defaultTheme: THEMES.DARK });

        expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('ignores a stored value that is not a known theme', () => {
        localStorage.setItem(THEME_KEY, 'banana');

        renderWithTheme({ defaultTheme: THEMES.DARK });

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });
});
