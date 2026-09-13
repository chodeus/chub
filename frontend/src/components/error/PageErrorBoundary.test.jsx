/** Guards PageErrorBoundary's copy-timer cleanup and its single statement of the page description. */
import { StrictMode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import PageErrorBoundary from './PageErrorBoundary.jsx';
import { ErrorProvider } from './ErrorContext.jsx';
import { copyText } from '../../utils/clipboard.js';

vi.mock('../../utils/clipboard.js', () => ({ copyText: vi.fn() }));

function Broken() {
    throw new Error('boom');
}

function deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

const renderPage = (props = {}) =>
    render(
        <StrictMode>
            <ErrorProvider>
                <PageErrorBoundary pageName="Settings" {...props}>
                    <Broken />
                </PageErrorBoundary>
            </ErrorProvider>
        </StrictMode>
    );

beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'group').mockImplementation(() => {});
    vi.spyOn(console, 'groupEnd').mockImplementation(() => {});
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    vi.useRealTimers();
});

describe('PageErrorBoundary', () => {
    it('states the page description once', () => {
        renderPage({ pageDescription: 'Settings form' });

        expect(screen.getAllByText(/settings form/i)).toHaveLength(1);
    });

    it('clears the copy-status timer on unmount', async () => {
        const view = renderPage();
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /Copy Error/ }));
        });
        expect(screen.getByRole('button', { name: /Copied!/ })).toBeInTheDocument();
        expect(vi.getTimerCount()).toBeGreaterThan(0);

        view.unmount();

        expect(vi.getTimerCount()).toBe(0);
    });

    it.each([
        ['resolves', copy => copy.resolve()],
        ['rejects', copy => copy.reject(new Error('denied'))],
    ])('ignores a copy that %s after unmount', async (_, settle) => {
        const copy = deferred();
        copyText.mockReturnValue(copy.promise);
        const view = renderPage();
        fireEvent.click(screen.getByRole('button', { name: /Copy Error/ }));
        view.unmount();
        vi.mocked(console.error).mockClear();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

        await act(async () => settle(copy));

        expect(vi.getTimerCount()).toBe(0);
        expect(console.error).not.toHaveBeenCalled();
        expect(warn).not.toHaveBeenCalled();
    });
});
