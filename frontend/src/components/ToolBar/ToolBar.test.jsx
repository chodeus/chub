/** Guards toolbar arrow-key navigation against hijacking keys typed into an input. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ToolBar from './ToolBar.jsx';

const renderToolBar = () =>
    render(
        <ToolBar>
            <input aria-label="Filter" />
            <ToolBar.Button label="Save" iconName="save" />
            <ToolBar.Button label="Reset" iconName="undo" />
        </ToolBar>
    );

describe('ToolBar keyboard navigation', () => {
    it('moves focus between buttons with the arrow keys', async () => {
        const user = userEvent.setup();
        renderToolBar();
        await user.click(screen.getByRole('button', { name: 'Save' }));

        await user.keyboard('{ArrowRight}');

        expect(screen.getByRole('button', { name: 'Reset' })).toHaveFocus();
    });

    it('leaves arrow keys typed in an input alone', async () => {
        const user = userEvent.setup();
        renderToolBar();
        const input = screen.getByRole('textbox', { name: 'Filter' });
        await user.click(input);

        await user.keyboard('{ArrowLeft}{ArrowRight}{Home}{End}');

        expect(input).toHaveFocus();
    });
});
