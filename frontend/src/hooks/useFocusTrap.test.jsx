/** Guards that the focus trap skips matches that cannot actually take focus. */
import { useRef } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { useFocusTrap } from './useFocusTrap.js';

const Trap = ({ children }) => {
    const ref = useRef(null);
    useFocusTrap(ref, true);
    return (
        <div ref={ref} tabIndex={-1} role="dialog">
            {children}
        </div>
    );
};

describe('useFocusTrap', () => {
    it('skips a display:none match and focuses the first visible control', () => {
        render(
            <Trap>
                <button type="button" style={{ display: 'none' }}>
                    Hidden
                </button>
                <button type="button">Visible</button>
            </Trap>
        );

        expect(screen.getByRole('button', { name: 'Visible' })).toHaveFocus();
    });

    it('skips a visibility:hidden match', () => {
        render(
            <Trap>
                <button type="button" style={{ visibility: 'hidden' }}>
                    Invisible
                </button>
                <button type="button">Visible</button>
            </Trap>
        );

        expect(screen.getByRole('button', { name: 'Visible' })).toHaveFocus();
    });

    it('skips a control inside an aria-hidden subtree', () => {
        render(
            <Trap>
                <div aria-hidden="true">
                    <button type="button">Decorative</button>
                </div>
                <button type="button">Visible</button>
            </Trap>
        );

        expect(screen.getByRole('button', { name: 'Visible' })).toHaveFocus();
    });

    it('still falls back to the container when every match is hidden', () => {
        render(
            <Trap>
                <button type="button" style={{ display: 'none' }}>
                    Hidden
                </button>
            </Trap>
        );

        expect(screen.getByRole('dialog')).toHaveFocus();
    });

    it('skips a control inside a display:none ancestor', () => {
        // `display` does not inherit, so the button computes its own value.
        render(
            <Trap>
                <div style={{ display: 'none' }}>
                    <button type="button">Buried</button>
                </div>
                <button type="button">Visible</button>
            </Trap>
        );

        expect(screen.getByRole('button', { name: 'Visible' })).toHaveFocus();
    });

    it('skips a control disabled by an ancestor fieldset', () => {
        // The control carries no disabled attribute of its own, so the selector matches it.
        render(
            <Trap>
                <fieldset disabled>
                    <button type="button">Locked</button>
                </fieldset>
                <button type="button">Visible</button>
            </Trap>
        );

        expect(screen.getByRole('button', { name: 'Visible' })).toHaveFocus();
    });

    it('refocuses when the focused control becomes aria-hidden', async () => {
        const { rerender } = render(
            <Trap>
                <div>
                    <button type="button">First</button>
                </div>
                <button type="button">Second</button>
            </Trap>
        );
        expect(screen.getByRole('button', { name: 'First' })).toHaveFocus();

        rerender(
            <Trap>
                <div aria-hidden="true">
                    <button type="button">First</button>
                </div>
                <button type="button">Second</button>
            </Trap>
        );

        await waitFor(() => expect(screen.getByRole('button', { name: 'Second' })).toHaveFocus());
    });
});
