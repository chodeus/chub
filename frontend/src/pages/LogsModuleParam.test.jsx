import { render } from '@testing-library/react';

const h = vi.hoisted(() => ({ search: '', modules: [], files: vi.fn(), content: vi.fn() }));

vi.mock('../contexts/UIStateContext', () => ({
    useUIState: () => ({ viewport: { width: 1400 } }),
}));
vi.mock('react-router', () => ({
    useSearchParams: () => [new URLSearchParams(h.search), vi.fn()],
}));
vi.mock('../hooks/useLogModules.js', () => ({ useLogModules: () => ({ modules: h.modules }) }));
vi.mock('../hooks/useLogFiles.js', () => ({ useLogFiles: h.files }));
vi.mock('../hooks/useLogContent.js', () => ({ useLogContent: h.content }));
vi.mock('../hooks/useLogPolling.js', () => ({ useLogPolling: () => {} }));
vi.mock('../components/logs/components/LogOutput.jsx', () => ({ LogOutput: () => <div /> }));
vi.mock('../utils/api/logs.js', () => ({ logsAPI: { downloadLogFile: vi.fn() } }));

const { default: Logs } = await import('./Logs.jsx');

// backend/api/logs.py allowlists the module too; these cover the request never
// being built, so a crafted name cannot reshape the URL in the first place.
describe('Logs ?module= boundary', () => {
    beforeEach(() => {
        h.search = '';
        h.modules = [];
        h.files.mockReset().mockReturnValue({
            logFiles: [],
            selectedLogFile: '',
            setSelectedLogFile: vi.fn(),
        });
        h.content.mockReset().mockReturnValue({
            logText: '',
            refresh: vi.fn(),
            inFlightRef: { current: false },
        });
    });

    it('never requests a module the backend did not list', () => {
        h.search = 'module=cleanarr/../../etc/passwd';
        h.modules = ['cleanarr'];

        render(<Logs />);

        expect(h.files).not.toHaveBeenCalledWith('cleanarr/../../etc/passwd');
        expect(h.content).not.toHaveBeenCalledWith('cleanarr/../../etc/passwd', expect.anything());
        expect(h.files).toHaveBeenCalledWith('');
    });

    it('requests nothing until the module list has loaded', () => {
        h.search = 'module=cleanarr';
        h.modules = [];

        render(<Logs />);

        expect(h.files).not.toHaveBeenCalledWith('cleanarr');
    });

    it('still deep-links into a listed module', () => {
        h.search = 'module=cleanarr';
        h.modules = ['cleanarr'];

        render(<Logs />);

        expect(h.files).toHaveBeenCalledWith('cleanarr');
    });
});
