/** Guards the overflow menu: an item click runs its action and closes the menu exactly once. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ToolBar from './ToolBar.jsx';

const VIEWPORTS = { mobile: 375, desktop: 1024 };

describe.each(Object.keys(VIEWPORTS))('ToolBar.Overflow (%s)', viewport => {
    const originalWidth = window.innerWidth;

    beforeEach(() => {
        window.innerWidth = VIEWPORTS[viewport];
        // jsdom lays nothing out; Dropdown closes itself when its anchor has no area.
        vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
            top: 0,
            left: 0,
            right: 80,
            bottom: 40,
            width: 80,
            height: 40,
            x: 0,
            y: 0,
        });
    });

    afterEach(() => {
        window.innerWidth = originalWidth;
    });

    const openMenu = async (user, onPress) => {
        render(
            <ToolBar>
                <ToolBar.Overflow overflowButtons={[{ key: 'del', label: 'Delete', onPress }]} />
            </ToolBar>
        );
        const toggle = screen.getByRole('button', { name: 'Show 1 more actions' });
        await user.click(toggle);
        expect(screen.getByRole('menu')).toBeInTheDocument();
        return toggle;
    };

    it('runs the clicked action and closes the menu', async () => {
        const user = userEvent.setup();
        const onPress = vi.fn();
        const toggle = await openMenu(user, onPress);

        await user.click(screen.getByRole('menuitem', { name: 'Delete' }));

        expect(onPress).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
    });

    it('closes on Escape', async () => {
        const user = userEvent.setup();
        const toggle = await openMenu(user, vi.fn());

        await user.keyboard('{Escape}');

        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
    });
});
