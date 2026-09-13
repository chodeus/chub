/** Guards section overflow: real Separators aren't counted as buttons, and no render-phase setState. */
import { act, render, screen } from '@testing-library/react';
import ToolBar from './ToolBar.jsx';

const renderFourButtons = () =>
    render(
        <ToolBar>
            <ToolBar.Section>
                {['one', 'two', 'three', 'four'].map(label => (
                    <ToolBar.Button key={label} label={label} iconName="add" />
                ))}
            </ToolBar.Section>
        </ToolBar>
    );

describe('ToolBar section overflow', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('does not count a Separator with props as a button', () => {
        const { container } = render(
            <ToolBar>
                <ToolBar.Section>
                    <ToolBar.Button label="A" iconName="add" />
                    <ToolBar.Separator className="mx-1" />
                    <ToolBar.Button label="B" iconName="remove" />
                </ToolBar.Section>
            </ToolBar>
        );
        const section = container.querySelector('[role="toolbar"] > div');
        expect(section.style.flexGrow).toBe('2');
    });

    it('overflows a narrow section without updating the provider during render', () => {
        vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100);
        const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

        renderFourButtons();

        expect(screen.getByRole('button', { name: /More \(3\)/ })).toBeInTheDocument();
        expect(errorSpy.mock.calls.flat().join('\n')).not.toMatch(/Cannot update a component/);
    });

    it('re-measures when the section resizes and disconnects on unmount', () => {
        const observers = [];
        vi.stubGlobal(
            'ResizeObserver',
            class {
                constructor(callback) {
                    this.callback = callback;
                    this.disconnect = vi.fn();
                    observers.push(this);
                }
                observe() {}
            }
        );
        let width = 1000;
        vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => width);

        const { unmount } = renderFourButtons();
        expect(screen.queryByRole('button', { name: /More/ })).not.toBeInTheDocument();

        width = 100;
        act(() => observers.forEach(observer => observer.callback([])));
        expect(screen.getByRole('button', { name: /More \(3\)/ })).toBeInTheDocument();

        unmount();
        expect(observers).toHaveLength(1);
        expect(observers[0].disconnect).toHaveBeenCalledTimes(1);
    });
});
