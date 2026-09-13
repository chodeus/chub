/** Guards the modal ErrorContainer's accessible name when the caller passes no title. */
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
});
