import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';

const toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
vi.mock('../../contexts/ToastContext', () => ({ useToast: () => toast }));

const { InstancesPage } = await import('./InstancesPage.jsx');

const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
    });

// Only HTTP and toasts are faked; the page, the card and apiCore are real.
const stubServer = server => {
    vi.stubGlobal(
        'fetch',
        vi.fn(async (url, init = {}) => {
            const path = String(url).split('?')[0];
            if (path.endsWith('/instances/test')) {
                const { service } = JSON.parse(init.body);
                return server.tokenWorks && service !== server.failingService
                    ? json({ success: true, message: 'Connection successful' })
                    : json({ success: false, message: 'Invalid credentials' }, 401);
            }
            if (path.endsWith('/instances/Chodeus/health')) {
                if (server.healthDown) return json({ success: false, message: 'down' }, 500);
                // Like the backend: without a service, the first match (Plex) answers.
                const service = new URL(url, 'http://chub').searchParams.get('service') || 'plex';
                const works = server.tokenWorks && service !== server.failingService;
                const status = works ? 'healthy' : 'unhealthy';
                return json({ success: true, data: { service, status } });
            }
            if (path.endsWith('/instances/Chodeus') && init.method === 'PUT') {
                server.saved = JSON.parse(init.body);
                return json({ success: true, message: 'updated' });
            }
            if (path.endsWith('/instances')) {
                const data = { plex: { Chodeus: { url: 'http://plex:32400', api: '***' } } };
                if (server.failingService) {
                    data[server.failingService] = { Chodeus: { url: 'http://s:8989', api: '***' } };
                }
                return json({ success: true, data });
            }
            return json({ success: true, data: {} });
        })
    );
};

const renderPage = async () => {
    render(
        <UIStateProvider>
            <InstancesPage />
        </UIStateProvider>
    );
    await screen.findAllByText('Chodeus');
};

const label = text => screen.findByText(text, { selector: 'span' });

describe('InstancesPage health badge', () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(() => vi.unstubAllGlobals());

    it('shows a health check that fails on page load', async () => {
        stubServer({ tokenWorks: false });
        await renderPage();
        expect(await label('unhealthy')).toBeInTheDocument();
    });

    it('replaces the page-load verdict when Test succeeds', async () => {
        const server = { tokenWorks: false };
        stubServer(server);
        await renderPage();
        await label('unhealthy');

        server.tokenWorks = true;
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));

        expect(await label('healthy')).toBeInTheDocument();
        expect(screen.queryByText('unhealthy')).toBeNull();
    });

    it('replaces the page-load verdict and the failed count after saving a new token', async () => {
        const server = { tokenWorks: false };
        stubServer(server);
        await renderPage();
        await label('unhealthy');

        fireEvent.click(screen.getByRole('button', { name: 'Edit instance' }));
        const dialog = await screen.findByRole('dialog');
        server.tokenWorks = true;
        fireEvent.change(within(dialog).getByLabelText(/api/i), { target: { value: 'new' } });
        fireEvent.click(within(dialog).getByRole('button', { name: /Save Changes/ }));

        expect(await label('healthy')).toBeInTheDocument();
        expect(server.saved.api).toBe('new');
        await waitFor(() => {
            const failed = screen.getByText('Failed').parentElement;
            expect(failed).toHaveTextContent('0');
        });
    });

    it('falls back to the Test result when the health check itself fails', async () => {
        const server = { tokenWorks: false };
        stubServer(server);
        await renderPage();
        await label('unhealthy');

        server.tokenWorks = true;
        server.healthDown = true;
        fireEvent.click(screen.getByRole('button', { name: 'Test' }));

        expect(await label('Healthy')).toBeInTheDocument();
    });

    it('gives same-named instances of two services their own verdicts', async () => {
        stubServer({ tokenWorks: true, failingService: 'sonarr' });
        await renderPage();

        expect(await label('healthy')).toBeInTheDocument();
        expect(await label('unhealthy')).toBeInTheDocument();
    });
});
