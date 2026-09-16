/** Guards that a disabled directory list cannot be dragged. */
import { render as rtlRender, fireEvent } from '@testing-library/react';
import { DndContext, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { UIStateProvider } from '../../../../contexts/UIStateContext.jsx';

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

vi.mock('../../../../utils/touchDetection', () => ({ useTouchDevice: () => false }));

const { DirectoryArray } = await import('./DirectoryArray.jsx');

function Harness({ disabled, onDragStart }) {
    const sensors = useSensors(
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    );
    return (
        <DndContext sensors={sensors} onDragStart={onDragStart}>
            <SortableContext items={['0', '1']}>
                <DirectoryArray
                    directories={['/a', '/b']}
                    onChange={() => {}}
                    baseId="dirs"
                    enableReordering
                    disabled={disabled}
                />
            </SortableContext>
        </DndContext>
    );
}

describe('DirectoryArray', () => {
    it.each([
        [false, 1],
        [true, 0],
    ])(
        'starts a keyboard drag from the handle only when enabled (disabled=%s)',
        (disabled, starts) => {
            const onDragStart = vi.fn();
            const { container } = render(<Harness disabled={disabled} onDragStart={onDragStart} />);
            const handle = container.querySelector('[aria-roledescription="sortable"]');

            fireEvent.keyDown(handle, { code: 'Space', key: ' ' });
            expect(onDragStart).toHaveBeenCalledTimes(starts);
        }
    );
});
