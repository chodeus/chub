/** Guards that the focus trap skips matches that cannot actually take focus. */
import { useRef } from 'react';
import { render, screen } from '@testing-library/react';
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
});
