/** Guards the modal ErrorContainer's accessible name, initial focus and focus trap. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorContainer } from './ErrorContainer.jsx';

describe('ErrorContainer', () => {
    it.each([
        ['omitted', undefined],
        ['empty', ''],
    ])('names the modal alert dialog when the title is %s', (_, title) => {
        render(
            <ErrorContainer mode="modal" title={title}>
                <button type="button">Retry</button>
            </ErrorContainer>
        );

        expect(screen.getByRole('alertdialog')).toHaveAccessibleName('Something went wrong');
    });

    it('focuses the dialog itself when it has no focusable child', () => {
        render(
            <ErrorContainer mode="modal" title="Critical">
                <p>Nothing to press</p>
            </ErrorContainer>
        );

        expect(screen.getByRole('alertdialog')).toHaveFocus();
    });

    it('still focuses the first button when there is one', () => {
        render(
            <ErrorContainer mode="modal" title="Critical">
                <button type="button">Retry</button>
            </ErrorContainer>
        );

        expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus();
    });

    it('keeps Tab and Shift+Tab inside a dialog with no focusable child', async () => {
        const user = userEvent.setup();
        render(
            <>
                <button type="button">Before</button>
                <ErrorContainer mode="modal" title="Critical">
                    <p>Nothing to press</p>
                </ErrorContainer>
                <button type="button">After</button>
            </>
        );
        const dialog = screen.getByRole('alertdialog');

        await user.tab();
        expect(dialog).toHaveFocus();
        await user.tab({ shift: true });
        expect(dialog).toHaveFocus();
    });

    it('wraps Shift+Tab from the dialog itself to its last button', async () => {
        const user = userEvent.setup();
        render(
            <>
                <button type="button">Before</button>
                <ErrorContainer mode="modal" title="Critical">
                    <button type="button">Retry</button>
                    <button type="button">Reload</button>
                </ErrorContainer>
            </>
        );

        screen.getByRole('alertdialog').focus();
        await user.tab({ shift: true });

        expect(screen.getByRole('button', { name: 'Reload' })).toHaveFocus();
    });

    it('pulls Tab back into the dialog after a click drops focus to the page', async () => {
        const user = userEvent.setup();
        render(
            <>
                <button type="button">Before</button>
                <ErrorContainer mode="modal" title="Critical">
                    <button type="button">Retry</button>
                    <button type="button">Reload</button>
                </ErrorContainer>
            </>
        );

        document.activeElement.blur();
        await user.tab();
        expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus();

        document.activeElement.blur();
        await user.tab({ shift: true });
        expect(screen.getByRole('button', { name: 'Reload' })).toHaveFocus();
    });

    it('lets only the newest of two open dialogs handle Tab', async () => {
        const user = userEvent.setup();
        render(
            <>
                <ErrorContainer mode="modal" title="Older">
                    <button type="button">Older action</button>
                </ErrorContainer>
                <ErrorContainer mode="modal" title="Newer">
                    <button type="button">One</button>
                    <button type="button">Two</button>
                </ErrorContainer>
            </>
        );

        expect(screen.getByRole('button', { name: 'One' })).toHaveFocus();
        await user.tab();

        expect(screen.getByRole('button', { name: 'Two' })).toHaveFocus();
    });
});
