import { render } from '@testing-library/react';
import { ThemeProvider, THEMES } from './ThemeContext.jsx';

const THEME_KEY = 'chub-theme-preference';

const renderWithTheme = props =>
    render(
        <ThemeProvider {...props}>
            <span>child</span>
        </ThemeProvider>
    );

describe('ThemeProvider', () => {
    beforeEach(() => {
        localStorage.clear();
        document.documentElement.removeAttribute('data-theme');
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
