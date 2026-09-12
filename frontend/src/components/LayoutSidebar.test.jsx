/** Guards the mobile drawer: top-level links close it, and the closed drawer is inert. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

const ui = vi.hoisted(() => ({ mobileMenuOpen: true, isMobile: true, closeMobileMenu: null }));
vi.mock('../contexts/UIStateContext.jsx', () => ({ useUIState: () => ui }));
vi.mock('../contexts/AuthContext.jsx', () => ({ useAuth: () => ({ user: 'dean', logout() {} }) }));
vi.mock('../contexts/ThemeContext.jsx', () => ({
    useTheme: () => ({
        toggleTheme() {},
        isDarkTheme: true,
        isLightTheme: false,
        actualTheme: 'dark',
    }),
}));
vi.mock('../hooks/useApiData', () => ({ useApiData: () => ({ data: null }) }));
vi.mock('../utils/api/system', () => ({ systemAPI: { getVersion() {} } }));

const LayoutSidebar = (await import('./LayoutSidebar.jsx')).default;

const renderSidebar = () =>
    render(
        <MemoryRouter initialEntries={['/dashboard']}>
            <LayoutSidebar />
        </MemoryRouter>
    );

describe('LayoutSidebar mobile drawer', () => {
    beforeEach(() => {
        ui.mobileMenuOpen = true;
        ui.closeMobileMenu = vi.fn();
    });

    it('closes the drawer when a top-level link is clicked', async () => {
        renderSidebar();
        await userEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
        expect(ui.closeMobileMenu).toHaveBeenCalledTimes(1);
    });

    it('keeps the drawer open when an expandable parent is clicked', async () => {
        renderSidebar();
        await userEvent.click(screen.getByRole('link', { name: 'Library' }));
        expect(ui.closeMobileMenu).not.toHaveBeenCalled();
    });

    it('makes the closed drawer inert', () => {
        ui.mobileMenuOpen = false;
        const { container } = renderSidebar();
        expect(container.querySelector('aside')).toHaveAttribute('inert');
    });
});
