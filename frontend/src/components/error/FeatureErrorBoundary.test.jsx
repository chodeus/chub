/** Guards FeatureErrorBoundary's retry limit, its reset after recovery, timer cleanup and a11y. */
import { useEffect } from 'react';
import { act, fireEvent, isInaccessible, render, screen } from '@testing-library/react';
import FeatureErrorBoundary from './FeatureErrorBoundary.jsx';
import { ErrorProvider } from './ErrorContext.jsx';

vi.mock('../../utils/clipboard.js', () => ({ copyText: vi.fn() }));

const PAST_RECOVERY_WINDOW = 60_000;
const flaky = { throws: true };

function Flaky() {
    if (flaky.throws) throw new Error('boom');
    return <p>feature ok</p>;
}

function ThrowsFromEffect() {
    useEffect(() => {
        throw new Error('effect boom');
    });
    return <p>mounted</p>;
}

function renderBoundary(child, props = {}) {
    const tree = c => (
        <ErrorProvider>
            <FeatureErrorBoundary featureName="Widget" {...props}>
                {c}
            </FeatureErrorBoundary>
        </ErrorProvider>
    );
    const view = render(tree(child));
    return { ...view, rerender: c => view.rerender(tree(c)) };
}

const clickRetry = () => fireEvent.click(screen.getByRole('button', { name: /Retry/ }));

beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'group').mockImplementation(() => {});
    vi.spyOn(console, 'groupEnd').mockImplementation(() => {});
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    flaky.throws = true;
});

afterEach(() => {
    vi.useRealTimers();
});

describe('FeatureErrorBoundary', () => {
    it('resets the retry count once a retried feature stays healthy', () => {
        const view = renderBoundary(<Flaky />);
        for (let i = 0; i < 3; i++) {
            flaky.throws = false;
            clickRetry();
            expect(screen.getByText('feature ok')).toBeInTheDocument();
            act(() => vi.advanceTimersByTime(PAST_RECOVERY_WINDOW));
            flaky.throws = true;
            view.rerender(<Flaky />);
        }

        expect(screen.queryByText('Widget temporarily disabled')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
    });

    it('still disables a feature whose child throws from an effect after every retry', () => {
        renderBoundary(<ThrowsFromEffect />);
        for (let i = 0; i < 3; i++) {
            clickRetry();
            act(() => vi.advanceTimersByTime(PAST_RECOVERY_WINDOW));
        }

        expect(screen.getByText('Widget temporarily disabled')).toBeInTheDocument();
    });

    it('offers a reload control once retries are exhausted', () => {
        renderBoundary(<Flaky />);
        clickRetry();
        clickRetry();
        clickRetry();

        expect(screen.getByText('Widget temporarily disabled')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Reload page' })).toBeInTheDocument();
        expect(isInaccessible(screen.getByText('warning'))).toBe(true);
    });

    it('keeps icon glyphs out of the inline error accessible text', () => {
        renderBoundary(<Flaky />);

        expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Skip' })).toBeInTheDocument();
        const glyphs = screen.getAllByText('warning');
        expect(glyphs).toHaveLength(2);
        glyphs.forEach(glyph => expect(isInaccessible(glyph)).toBe(true));
    });

    it('keeps icon glyphs out of the skipped-state accessible text', () => {
        renderBoundary(<Flaky />);
        fireEvent.click(screen.getByRole('button', { name: /Skip/ }));

        expect(screen.getByText('Widget skipped due to error')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
        expect(isInaccessible(screen.getByText('skip_next'))).toBe(true);
    });

    it('clears the copy-status timer on unmount', async () => {
        const view = renderBoundary(<Flaky />);
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /Copy Error/ }));
        });
        expect(screen.getByRole('button', { name: /Copied!/ })).toBeInTheDocument();
        expect(vi.getTimerCount()).toBeGreaterThan(0);

        view.unmount();

        expect(vi.getTimerCount()).toBe(0);
    });

    it('renders a critical error as a labelled alert dialog holding focus', () => {
        renderBoundary(<Flaky />, { critical: true });
        const dialog = screen.getByRole('alertdialog', { name: 'Critical Feature Error' });

        expect(dialog).toHaveAttribute('aria-modal', 'true');
        expect(dialog).toHaveAccessibleDescription(/Widget feature is required/);
        expect(dialog).toContainElement(document.activeElement);
    });
});
