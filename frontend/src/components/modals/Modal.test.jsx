/** Guards Escape and the focus trap across stacked and non-closable Modals. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';
import { ErrorContainer } from '../error/primitives/ErrorContainer.jsx';
import { Modal } from './Modal.jsx';

beforeEach(() => {
    const root = document.createElement('div');
    root.id = 'modal-root';
    document.body.append(root);
});

afterEach(() => document.getElementById('modal-root')?.remove());

describe('Modal', () => {
    it('closes on Escape when it is the top dialog', async () => {
        const onClose = vi.fn();
        render(
            <Modal isOpen onClose={onClose}>
                <button type="button">Save</button>
            </Modal>,
            { wrapper: UIStateProvider }
        );

        await userEvent.setup().keyboard('{Escape}');

        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('ignores Escape while the critical error dialog is on top', async () => {
        const onClose = vi.fn();
        render(
            <>
                <Modal isOpen onClose={onClose}>
                    <button type="button">Save</button>
                </Modal>
                <ErrorContainer mode="modal" title="Critical">
                    <button type="button">Retry</button>
                </ErrorContainer>
            </>,
            { wrapper: UIStateProvider }
        );

        await userEvent.setup().keyboard('{Escape}');

        expect(onClose).not.toHaveBeenCalled();
    });

    it('keeps focus inside while it turns non-closable during a save', () => {
        const opener = (
            <button key="opener" type="button">
                Opener
            </button>
        );
        const modal = closable => (
            <Modal key="modal" isOpen closable={closable} onClose={() => {}}>
                <button type="button">Save</button>
            </Modal>
        );
        const { rerender } = render(<>{[opener]}</>, { wrapper: UIStateProvider });
        screen.getByRole('button', { name: 'Opener' }).focus();
        rerender(<>{[opener, modal(true)]}</>);
        expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus();

        rerender(<>{[opener, modal(false)]}</>);

        expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus();
    });

    it('leaves the modal underneath open when Escape is pressed in a non-closable one', async () => {
        const onClose = vi.fn();
        render(
            <>
                <Modal isOpen onClose={onClose}>
                    <button type="button">Save</button>
                </Modal>
                <Modal isOpen closable={false}>
                    <button type="button">Wait</button>
                </Modal>
            </>,
            { wrapper: UIStateProvider }
        );

        await userEvent.setup().keyboard('{Escape}');

        expect(onClose).not.toHaveBeenCalled();
    });
});
