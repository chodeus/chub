/** Guards ItemCounter's status colours, and that RemoveButton leaks no `variant` attribute. */
import { render, screen } from '@testing-library/react';
import { ItemCounter } from './ItemCounter.jsx';
import { RemoveButton } from './RemoveButton.jsx';
import { ColorArray } from '../color/ColorArray.jsx';

describe('ItemCounter', () => {
    it('styles the warning and full states differently', () => {
        const { rerender, container } = render(<ItemCounter current={8} total={10} />);
        expect(container.firstChild).toHaveClass('text-warning');

        rerender(<ItemCounter current={10} total={10} />);
        expect(container.firstChild).toHaveClass('text-error');
    });
});

describe('RemoveButton', () => {
    it('hides the icon ligature from assistive technology', () => {
        render(<RemoveButton itemName="color 1" onClick={() => {}} />);
        const icon = screen.getByRole('button', { name: 'Remove color 1' }).firstChild;
        expect(icon).toHaveAttribute('aria-hidden', 'true');
    });

    it('receives no variant from ColorArray', () => {
        render(<ColorArray colors={['#000000', '#ffffff']} onChange={() => {}} baseId="c" />);
        expect(screen.getByRole('button', { name: 'Remove colors 1' })).not.toHaveAttribute(
            'variant'
        );
    });
});
