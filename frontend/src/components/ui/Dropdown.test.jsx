import { useRef } from 'react';
import { render, screen } from '@testing-library/react';

// jsdom gives every element a zero-sized rect, so the real isElementVisible
// reports false and the dropdown closes itself before anything can be asserted.
vi.mock('../../utils/positioning', () => ({
    calculateOptimalPosition: () => ({ top: 0, left: 0 }),
    isElementVisible: () => true,
}));

const { default: Dropdown } = await import('./Dropdown.jsx');

const Harness = ({ open }) => {
    const anchorRef = useRef(null);
    return (
        <>
            <button ref={anchorRef} data-testid="anchor" type="button">
                open
            </button>
            <Dropdown isOpen={open} onClose={() => {}} anchorRef={anchorRef}>
                <button data-testid="item" type="button">
                    item
                </button>
            </Dropdown>
        </>
    );
};

describe('Dropdown focus handling', () => {
    it('moves focus into the dropdown when it opens', () => {
        render(<Harness open />);

        expect(document.activeElement).toBe(screen.getByTestId('item'));
    });

    it('hands focus back to the anchor when it closes', () => {
        const { rerender } = render(<Harness open />);
        expect(document.activeElement).toBe(screen.getByTestId('item'));

        rerender(<Harness open={false} />);

        // Closing unmounts the focused element, orphaning focus on the body.
        expect(document.activeElement).toBe(screen.getByTestId('anchor'));
    });

    it('leaves focus alone when the user moved it somewhere else', () => {
        const { rerender } = render(
            <>
                <input data-testid="elsewhere" />
                <Harness open />
            </>
        );
        screen.getByTestId('elsewhere').focus();

        rerender(
            <>
                <input data-testid="elsewhere" />
                <Harness open={false} />
            </>
        );

        expect(document.activeElement).toBe(screen.getByTestId('elsewhere'));
    });
});
