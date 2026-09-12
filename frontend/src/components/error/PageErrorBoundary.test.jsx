/** Guards PageErrorBoundary's copy-timer cleanup and its single statement of the page description. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import PageErrorBoundary from './PageErrorBoundary.jsx';
import { ErrorProvider } from './ErrorContext.jsx';

vi.mock('../../utils/clipboard.js', () => ({ copyText: vi.fn() }));

function Broken() {
    throw new Error('boom');
}

const renderPage = (props = {}) =>
    render(
        <ErrorProvider>
            <PageErrorBoundary pageName="Settings" {...props}>
                <Broken />
            </PageErrorBoundary>
        </ErrorProvider>
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
});
