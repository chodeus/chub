import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmProvider, useConfirm } from './ConfirmContext.jsx';
import { UIStateProvider } from './UIStateContext.jsx';

// The dialog is a Modal, which reads UI state — the same nesting App.jsx uses.
const withProviders = ui => (
    <UIStateProvider>
        <ConfirmProvider>{ui}</ConfirmProvider>
    </UIStateProvider>
);

/** Calls confirm() on click and records how the promise settled. */
function Harness({ settled, options = 'Are you sure?' }) {
    const confirm = useConfirm();
    return <button onClick={async () => settled(await confirm(options))}>ask</button>;
}

const renderHarness = (props = {}) => {
    const settled = vi.fn();
    const view = render(withProviders(<Harness settled={settled} {...props} />));
    return { settled, ...view };
};

describe('useConfirm', () => {
    it('resolves true when confirmed and false when cancelled', async () => {
        const user = userEvent.setup();
        const { settled } = renderHarness();

        await user.click(screen.getByRole('button', { name: 'ask' }));
        await user.click(screen.getByRole('button', { name: 'Confirm' }));
        await waitFor(() => expect(settled).toHaveBeenLastCalledWith(true));

        await user.click(screen.getByRole('button', { name: 'ask' }));
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        await waitFor(() => expect(settled).toHaveBeenLastCalledWith(false));
    });

    it('closes the dialog once answered', async () => {
        const user = userEvent.setup();
        renderHarness();

        await user.click(screen.getByRole('button', { name: 'ask' }));
        expect(screen.getByText('Are you sure?')).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'Confirm' }));

        await waitFor(() => expect(screen.queryByText('Are you sure?')).not.toBeInTheDocument());
    });

    it('declines on Escape rather than leaving the caller hanging', async () => {
        const user = userEvent.setup();
        const { settled } = renderHarness();

        await user.click(screen.getByRole('button', { name: 'ask' }));
        await user.keyboard('{Escape}');

        await waitFor(() => expect(settled).toHaveBeenCalledWith(false));
    });

    // Without the resolverRef handover, the first caller awaits a promise that
    // nothing can ever settle.
    it('settles a superseded request when a second confirm opens', async () => {
        const user = userEvent.setup();
        const first = vi.fn();
        const second = vi.fn();

        function Two() {
            const confirm = useConfirm();
            return (
                <>
                    <button onClick={async () => first(await confirm('first?'))}>one</button>
                    <button onClick={async () => second(await confirm('second?'))}>two</button>
                </>
            );
        }

        render(withProviders(<Two />));

        await user.click(screen.getByRole('button', { name: 'one' }));
        await user.click(screen.getByRole('button', { name: 'two' }));

        await waitFor(() => expect(first).toHaveBeenCalledWith(false));
        expect(second).not.toHaveBeenCalled();

        await user.click(screen.getByRole('button', { name: 'Confirm' }));
        await waitFor(() => expect(second).toHaveBeenCalledWith(true));
    });

    // Unmounting with a dialog open must not strand the awaiting caller.
    it('settles an open request when the provider unmounts', async () => {
        const user = userEvent.setup();
        const { settled, unmount } = renderHarness();

        await user.click(screen.getByRole('button', { name: 'ask' }));
        expect(screen.getByText('Are you sure?')).toBeInTheDocument();
        unmount();

        await waitFor(() => expect(settled).toHaveBeenCalledWith(false));
    });

    it('accepts an options object for the labels and title', async () => {
        const user = userEvent.setup();
        renderHarness({
            options: {
                title: 'Delete collection',
                message: 'Poster files will not be removed.',
                confirmLabel: 'Delete',
                cancelLabel: 'Keep',
            },
        });

        await user.click(screen.getByRole('button', { name: 'ask' }));

        expect(screen.getByText('Delete collection')).toBeInTheDocument();
        expect(screen.getByText('Poster files will not be removed.')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Keep' })).toBeInTheDocument();
    });

    it('throws when used outside a provider', () => {
        const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
        expect(() =>
            render(
                <UIStateProvider>
                    <Harness settled={vi.fn()} />
                </UIStateProvider>
            )
        ).toThrow(/ConfirmProvider/);
        spy.mockRestore();
    });
});
