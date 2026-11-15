import { render, screen } from '@testing-library/react';

const mockUIState = { viewport: { width: 1400 } };
vi.mock('../contexts/UIStateContext', () => ({ useUIState: () => mockUIState }));
vi.mock('react-router', () => ({ useSearchParams: () => [new URLSearchParams(''), vi.fn()] }));
vi.mock('../hooks/useLogModules.js', () => ({ useLogModules: () => ({ modules: ['cleanarr'] }) }));
vi.mock('../hooks/useLogFiles.js', () => ({
    useLogFiles: () => ({
        logFiles: ['cleanarr.log'],
        selectedLogFile: 'cleanarr.log',
        setSelectedLogFile: vi.fn(),
    }),
}));
const mockContent = {
    logText: 'a line',
    skippedBytes: 0,
    refresh: vi.fn(),
    inFlightRef: { current: false },
};
vi.mock('../hooks/useLogContent.js', () => ({ useLogContent: () => mockContent }));
// Spread the real module: LOG_POLL_INTERVAL_MS must come from the hook that
// owns it, or the badge assertion below tests a number written twice.
vi.mock('../hooks/useLogPolling.js', async importOriginal => ({
    ...(await importOriginal()),
    useLogPolling: () => {},
}));
vi.mock('../components/logs/components/LogOutput.jsx', () => ({ LogOutput: () => <div /> }));
vi.mock('../utils/api/logs.js', () => ({ logsAPI: { downloadLogFile: vi.fn() } }));

const { default: Logs } = await import('./Logs.jsx');

const pressFind = () => {
    const event = new KeyboardEvent('keydown', {
        key: 'f',
        metaKey: true,
        bubbles: true,
        cancelable: true,
    });
    window.dispatchEvent(event);
    return event;
};

describe('Logs ⌘F shortcut', () => {
    afterEach(() => {
        window.innerWidth = 1024;
        mockUIState.viewport = { width: 1400 };
    });

    it('focuses and selects the filter field', () => {
        render(<Logs />);

        const event = pressFind();

        expect(document.activeElement).toBe(screen.getByLabelText('Search logs'));
        expect(event.defaultPrevented).toBe(true);
    });

    it('leaves browser find alone when there is no field to focus', () => {
        // Phone width, so the control panel mounts collapsed and renders no input.
        window.innerWidth = 500;
        mockUIState.viewport = { width: 900 };

        render(<Logs />);
        expect(screen.queryByLabelText('Search logs')).toBeNull();

        expect(pressFind().defaultPrevented).toBe(false);
    });
});

describe('Logs live-tail badge', () => {
    it('reports the interval useLogPolling actually polls on, not a hardcoded 1s', () => {
        render(<Logs />);

        expect(screen.getByText(/live tail · 5s/)).toBeTruthy();
        expect(screen.queryByText(/live tail · 1s/)).toBeNull();
    });
});

describe('Logs large-file notice', () => {
    afterEach(() => {
        mockContent.skippedBytes = 0;
    });

    it('says the top of the log was left out when the server skipped some of it', () => {
        mockContent.skippedBytes = 4096;
        render(<Logs />);

        expect(screen.getByText(/Showing only the end of this large log/)).toBeTruthy();
    });

    it('says nothing when the whole log is shown', () => {
        render(<Logs />);

        expect(screen.queryByText(/Showing only the end/)).toBeNull();
    });
});
