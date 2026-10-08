import { render as rtlRender, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';

const auth = { authConfigured: true, user: 'dean', setup: vi.fn(), disableAuth: vi.fn() };
const toast = { success: vi.fn(), error: vi.fn() };
vi.mock('../../contexts/AuthContext.jsx', () => ({ useAuth: () => auth }));
vi.mock('../../contexts/ToastContext', () => ({ useToast: () => toast }));

const AccessCard = (await import('./AccessCard.jsx')).default;

// Modal reads UI state (mobile bottom sheet), so it needs the real provider.
const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

const type = (label, value) =>
    fireEvent.change(within(screen.getByRole('dialog')).getByLabelText(label), {
        target: { value },
    });
const confirmIn = name =>
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name }));

describe('AccessCard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        auth.authConfigured = true;
        auth.disableAuth.mockResolvedValue({});
        auth.setup.mockResolvedValue({});
    });

    it('renders nothing until the auth status is known', () => {
        auth.authConfigured = null;
        const { container } = render(<AccessCard />);
        expect(container).toBeEmptyDOMElement();
    });

    it('turns the login off with the current password', async () => {
        render(<AccessCard />);
        fireEvent.click(screen.getByRole('button', { name: 'Turn off login' }));
        type('Current password', 'hunter2hunter2');
        confirmIn(/Turn off login/);

        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Login turned off'));
        expect(auth.disableAuth).toHaveBeenCalledWith('hunter2hunter2');
        expect(screen.queryByRole('dialog')).toBeNull();
    });

    it('keeps the dialog open and shows why when the password is wrong', async () => {
        auth.disableAuth.mockRejectedValue(new Error('Incorrect password'));
        render(<AccessCard />);
        fireEvent.click(screen.getByRole('button', { name: 'Turn off login' }));
        type('Current password', 'wrong');
        confirmIn(/Turn off login/);

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Incorrect password'));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('turns the login back on with a new username and password', async () => {
        auth.authConfigured = false;
        render(<AccessCard />);
        expect(screen.getByText(/The login is off/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /Turn on login/ }));
        type('Username', ' dean ');
        type('Password', 'a-new-password');
        type('Confirm password', 'a-new-password');
        confirmIn(/Turn on login/);

        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Login turned on'));
        expect(auth.setup).toHaveBeenCalledWith('dean', 'a-new-password');
    });

    it('does not create a login when the passwords differ', () => {
        auth.authConfigured = false;
        render(<AccessCard />);
        fireEvent.click(screen.getByRole('button', { name: /Turn on login/ }));
        type('Username', 'dean');
        type('Password', 'a-new-password');
        type('Confirm password', 'another-password');
        confirmIn(/Turn on login/);

        expect(toast.error).toHaveBeenCalledWith('Passwords do not match');
        expect(auth.setup).not.toHaveBeenCalled();
    });
});
