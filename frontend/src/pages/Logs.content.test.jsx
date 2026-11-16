/** What the Logs page shows for a read: useLogContent and logsAPI run for real over a stubbed fetch; the selection is fixed and polls run by hand. */
import { act, render, screen } from '@testing-library/react';

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
const polling = vi.hoisted(() => ({ refresh: null }));
vi.mock('../hooks/useLogPolling.js', async importOriginal => ({
    ...(await importOriginal()),
    useLogPolling: (_module, _file, refresh) => {
        polling.refresh = refresh;
    },
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

    it('keeps the log on screen and says when a poll fails', async () => {
        // jsdom has no layout: give the virtualized output a height so its lines render.
        vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(600);
        vi.stubGlobal(
            'fetch',
            reply('INFO first line\n', {
                'X-Log-Offset': '16',
                'X-Log-Id': '1:a',
                'X-Log-Start': '0',
                'X-Log-Reset': '1',
            })
        );
        render(<Logs />);
        expect(await screen.findByText(/first line/)).toBeTruthy();

        const failed = reply('', {}, 503);
        vi.stubGlobal('fetch', failed);
        await act(() => polling.refresh());

        expect(failed.mock.calls[0][0]).toContain('offset=16');
        expect(screen.getAllByRole('alert').map(a => a.textContent)).toEqual([
            'Could not refresh this log: Log request failed with status 503',
        ]);
        expect(screen.getByText(/first line/)).toBeTruthy();
        expect(screen.queryByText('No logs available')).toBeNull();
    });
});
