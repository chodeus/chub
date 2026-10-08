/** Guards the mobile drawer: top-level links close it, and the closed drawer is inert. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

const ui = vi.hoisted(() => ({ mobileMenuOpen: true, isMobile: true, closeMobileMenu: null }));
vi.mock('../contexts/UIStateContext.jsx', () => ({ useUIState: () => ui }));
const auth = vi.hoisted(() => ({ user: 'dean', logout() {}, authConfigured: true }));
vi.mock('../contexts/AuthContext.jsx', () => ({ useAuth: () => auth }));
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

describe('LayoutSidebar login state', () => {
    beforeEach(() => {
        ui.mobileMenuOpen = true;
        ui.closeMobileMenu = vi.fn();
    });
    afterEach(() => {
        Object.assign(auth, { user: 'dean', authConfigured: true });
    });

    it('points to Settings when the login is off, and closes the drawer on the way', async () => {
        Object.assign(auth, { user: null, authConfigured: false });
        renderSidebar();

        const link = screen.getByRole('link', { name: /Login off/ });
        expect(link).toHaveAttribute('href', '/settings/general');
        expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull();
        await userEvent.click(link);
        expect(ui.closeMobileMenu).toHaveBeenCalledTimes(1);
    });

    it('shows no login-off link while a login exists or the status is loading', () => {
        renderSidebar();
        expect(screen.queryByRole('link', { name: /Login off/ })).toBeNull();

        Object.assign(auth, { user: null, authConfigured: null });
        renderSidebar();
        expect(screen.queryByRole('link', { name: /Login off/ })).toBeNull();
    });
});
