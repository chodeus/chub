import { render, screen, act, fireEvent } from '@testing-library/react';

const mockClipboard = { copyText: vi.fn() };
vi.mock('../../../utils/clipboard.js', () => mockClipboard);

const { ActionButtons } = await import('./ActionButtons.jsx');
const { LogControlsProvider } = await import('../context/LogControlsContext.jsx');

const renderButtons = () =>
    render(
        <LogControlsProvider onDownload={vi.fn()}>
            <ActionButtons logText="a line" />
        </LogControlsProvider>
    );

const clickCopy = async () => {
    await act(async () => {
        fireEvent.click(screen.getByLabelText('Copy log to clipboard'));
    });
};

describe('ActionButtons', () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it('copies the log and confirms it', async () => {
        mockClipboard.copyText.mockResolvedValue(undefined);

        renderButtons();
        await clickCopy();

        expect(mockClipboard.copyText).toHaveBeenCalledWith('a line');
        expect(screen.getByLabelText('Copied to clipboard')).toBeInTheDocument();
    });

    it('drops the confirmation timer when it unmounts mid-countdown', async () => {
        vi.useFakeTimers();
        mockClipboard.copyText.mockResolvedValue(undefined);

        const { unmount } = renderButtons();
        await clickCopy();
        expect(vi.getTimerCount()).toBe(1);

        unmount();

        expect(vi.getTimerCount()).toBe(0);
    });
});
