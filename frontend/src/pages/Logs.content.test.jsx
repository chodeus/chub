/** What the Logs page shows for a read, through the real useLogContent and logsAPI; fetch is the only stub. */
import { render, screen } from '@testing-library/react';

vi.mock('../contexts/UIStateContext', () => ({
    useUIState: () => ({ viewport: { width: 1400 } }),
}));
vi.mock('react-router', () => ({
    useSearchParams: () => [new URLSearchParams('module=cleanarr'), vi.fn()],
}));
vi.mock('../hooks/useLogModules.js', () => ({ useLogModules: () => ({ modules: ['cleanarr'] }) }));
vi.mock('../hooks/useLogFiles.js', () => ({
    useLogFiles: () => ({
        logFiles: ['cleanarr.log'],
        selectedLogFile: 'cleanarr.log',
        setSelectedLogFile: vi.fn(),
    }),
}));
vi.mock('../hooks/useLogPolling.js', async importOriginal => ({
    ...(await importOriginal()),
    useLogPolling: () => {},
}));

const { default: Logs } = await import('./Logs.jsx');

const reply = (text, headers, status = 200) =>
    vi.fn(async () => ({
        ok: status < 400,
        status,
        text: async () => text,
        headers: new Headers(headers),
    }));

describe('Logs page reading a log', () => {
    beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}));
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('says a refused read failed instead of showing an empty log', async () => {
        vi.stubGlobal('fetch', reply('', {}, 403));
        render(<Logs />);

        expect((await screen.findByRole('alert')).textContent).toBe(
            'Could not load this log: Log request failed with status 403'
        );
        expect(screen.queryByText('No logs available')).toBeNull();
    });

    it('names the header a reply was missing', async () => {
        vi.stubGlobal('fetch', reply('INFO whole file\n', {}));
        render(<Logs />);

        expect((await screen.findByRole('alert')).textContent).toBe(
            'Could not load this log: Log response has no X-Log-Offset header'
        );
    });

    it('shows a large log with the notice and no error', async () => {
        vi.stubGlobal(
            'fetch',
            reply('INFO tail line\n', {
                'X-Log-Offset': '900',
                'X-Log-Id': '1:a',
                'X-Log-Start': '885',
                'X-Log-Reset': '1',
            })
        );
        render(<Logs />);

        expect(await screen.findByText(/Showing only the end of this large log/)).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
    });
});
