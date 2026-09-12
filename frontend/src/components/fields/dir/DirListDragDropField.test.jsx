/** Guards drag-end against a drop with no target, and the explicit 0 minimum. */
import { render } from '@testing-library/react';

const captured = vi.hoisted(() => ({}));

vi.mock('@dnd-kit/core', async importOriginal => ({
    ...(await importOriginal()),
    DndContext: ({ onDragEnd, children }) => {
        captured.onDragEnd = onDragEnd;
        return children;
    },
}));
vi.mock('@dnd-kit/sortable', async importOriginal => ({
    ...(await importOriginal()),
    SortableContext: ({ children }) => children,
}));
vi.mock('../features/dir', () => ({
    DirectoryArray: props => {
        captured.arrayProps = props;
        return null;
    },
}));

const { DirListDragDropField } = await import('./DirListDragDropField.jsx');

const field = { key: 'source_dirs', label: 'Source Dirs' };

describe('DirListDragDropField', () => {
    it('ignores a drop outside any target', () => {
        const onChange = vi.fn();
        render(<DirListDragDropField field={field} value={['/a', '/b']} onChange={onChange} />);

        expect(() => captured.onDragEnd({ active: { id: '0' }, over: null })).not.toThrow();
        expect(onChange).not.toHaveBeenCalled();
    });

    it('still reorders on a drop over another row', () => {
        const onChange = vi.fn();
        render(<DirListDragDropField field={field} value={['/a', '/b']} onChange={onChange} />);

        captured.onDragEnd({ active: { id: '0' }, over: { id: '1' } });
        expect(onChange).toHaveBeenCalledWith(['/b', '/a']);
    });

    it('keeps an explicit min_directories of 0', () => {
        render(
            <DirListDragDropField
                field={{ ...field, min_directories: 0 }}
                value={['/a']}
                onChange={() => {}}
            />
        );
        expect(captured.arrayProps.minDirectories).toBe(0);
    });
});
