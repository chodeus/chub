/** Guards the removable badge's keyboard contract, and that it is not announced as a toggle. */
import { render, screen, fireEvent } from '@testing-library/react';
import { Badge } from './Badge.jsx';

const badge = () => screen.getByText('logo').closest('[role="button"]');

describe('Badge', () => {
    it.each(['Enter', ' '])('removes on %j when it has no click handler', key => {
        const onRemove = vi.fn();
        render(<Badge onRemove={onRemove}>logo</Badge>);

        fireEvent.keyDown(badge(), { key });
        expect(onRemove).toHaveBeenCalledTimes(1);
    });

    it('is not exposed as a toggle button', () => {
        render(
            <Badge onRemove={() => {}} focused>
                logo
            </Badge>
        );
        expect(badge()).not.toHaveAttribute('aria-pressed');
    });
});
