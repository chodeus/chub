/** Guards that Escape closes only the top dialog. */
import { render } from '@testing-library/react';
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
});
