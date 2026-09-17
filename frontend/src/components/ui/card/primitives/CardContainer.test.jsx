import { render, screen } from '@testing-library/react';
import { CardContainer } from './CardContainer.jsx';

describe('CardContainer', () => {
    it('does not claim a pressed state on a card that is not a button', () => {
        const { container } = render(
            <CardContainer selected>
                <span>content</span>
            </CardContainer>
        );

        // aria-pressed on a plain div is invalid ARIA — it belongs to a button role.
        expect(container.firstChild).not.toHaveAttribute('aria-pressed');
    });

    it('reports the pressed state on a clickable card', () => {
        render(
            <CardContainer selected clickable onClick={() => {}} aria-label="Pick me">
                <span>content</span>
            </CardContainer>
        );

        expect(screen.getByRole('button', { name: 'Pick me' })).toHaveAttribute(
            'aria-pressed',
            'true'
        );
    });

    it('omits aria-pressed on a clickable card that is not selected', () => {
        render(
            <CardContainer clickable onClick={() => {}} aria-label="Pick me">
                <span>content</span>
            </CardContainer>
        );

        expect(screen.getByRole('button', { name: 'Pick me' })).not.toHaveAttribute('aria-pressed');
    });
});
