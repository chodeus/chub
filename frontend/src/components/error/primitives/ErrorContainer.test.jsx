/** Guards the modal ErrorContainer's accessible name and initial focus. */
import { render, screen } from '@testing-library/react';
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
});
