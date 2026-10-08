import { render, screen, fireEvent, act } from '@testing-library/react';

const auth = { authConfigured: false, setup: vi.fn(), markSetupComplete: vi.fn() };
vi.mock('react-router', () => ({ useNavigate: () => vi.fn() }));
vi.mock('../contexts/AuthContext.jsx', () => ({ useAuth: () => auth }));
vi.mock('../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));
vi.mock('../hooks/useDocumentTitle.js', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('../utils/api/instances.js', () => ({
    instancesAPI: { fetchInstances: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../utils/api/config.js', () => ({
    configAPI: { fetchConfig: vi.fn().mockResolvedValue({}) },
}));

const SetupWizardPage = (await import('./SetupWizardPage.jsx')).default;

const renderWizard = async () => {
    await act(async () => {
        render(<SetupWizardPage />);
    });
};
const railStep = title => screen.getByText(title, { selector: '.sw-t' }).closest('button');

describe('SetupWizardPage login choice', () => {
    beforeEach(() => {
        auth.authConfigured = false;
    });

    it('counts "No login" as a finished account step and warns about it', async () => {
        await renderWizard();
        fireEvent.click(railStep('User account'));
        expect(railStep('User account')).not.toHaveClass('done');

        fireEvent.click(screen.getByRole('radio', { name: /No login/ }));

        expect(railStep('User account')).toHaveClass('done');
        expect(screen.getByText(/Anyone who can reach CHUB can use it/)).toBeInTheDocument();
        expect(screen.queryByLabelText('Username')).toBeNull();

        fireEvent.click(railStep('Review'));
        expect(screen.getByText(/No login — open to anyone/)).toBeInTheDocument();
    });

    it('asks for a login by default', async () => {
        await renderWizard();
        fireEvent.click(railStep('User account'));

        expect(screen.getByRole('radio', { name: /Require a login/ })).toBeChecked();
        expect(screen.getByLabelText('Username')).toBeInTheDocument();
    });

    it('offers no choice once a login exists', async () => {
        auth.authConfigured = true;
        await renderWizard();
        fireEvent.click(railStep('User account'));

        expect(screen.queryByRole('radio')).toBeNull();
        expect(screen.getByText(/User account is configured/)).toBeInTheDocument();
    });
});
