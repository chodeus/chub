/** Guards the badge's control model: one focusable control per action, and no toggle semantics. */
import { render, screen, fireEvent } from '@testing-library/react';
import { Badge } from './Badge.jsx';

const wrapper = () => screen.getByText('logo').parentElement;

describe('Badge', () => {
    it('exposes the remove button as the only control when there is no click handler', () => {
        render(<Badge onRemove={() => {}}>logo</Badge>);

        const buttons = screen.getAllByRole('button');
        expect(buttons).toHaveLength(1);
        expect(buttons[0]).toHaveAccessibleName('Remove item: logo');
        expect(buttons[0]).not.toHaveAttribute('tabindex');
        expect(wrapper()).not.toHaveAttribute('role');
    });

    it('removes when its remove button is activated', () => {
        const onRemove = vi.fn();
        render(<Badge onRemove={onRemove}>logo</Badge>);

        fireEvent.click(screen.getByRole('button', { name: 'Remove item: logo' }));

        expect(onRemove).toHaveBeenCalledTimes(1);
    });

    it('keeps button semantics and Enter for a click-only badge', () => {
        const onClick = vi.fn();
        render(<Badge onClick={onClick}>logo</Badge>);
        const badge = wrapper();

        expect(badge).toHaveAttribute('role', 'button');
        fireEvent.keyDown(badge, { key: 'Enter' });

        expect(onClick).toHaveBeenCalledTimes(1);
    });

    it('refuses both callbacks rather than nesting controls', () => {
        const onClick = vi.fn();
        const onRemove = vi.fn();
        const error = vi.spyOn(console, 'error').mockImplementation(() => {});
        render(
            <Badge onClick={onClick} onRemove={onRemove}>
                logo
            </Badge>
        );

        expect(wrapper()).not.toHaveAttribute('role');
        expect(screen.getAllByRole('button')).toHaveLength(1);
        fireEvent.click(wrapper());
        expect(onClick).not.toHaveBeenCalled();
        expect(error).toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Remove item: logo' }));
        expect(onRemove).toHaveBeenCalledTimes(1);
        error.mockRestore();
    });

    it('is not exposed as a toggle button', () => {
        render(
            <Badge onClick={() => {}} focused>
                logo
            </Badge>
        );

        expect(wrapper()).not.toHaveAttribute('aria-pressed');
    });
});
