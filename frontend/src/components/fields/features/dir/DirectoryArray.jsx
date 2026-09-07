/**
 * DirectoryArray Composed Component
 *
 * Composed component for managing multiple directory values using atomic primitives.
 * Follows the same pattern as ColorArray for consistency.
 *
 * Composition Architecture:
 * - AddButton: Generic add functionality
 * - RemoveButton: Generic remove functionality
 * - ItemCounter: Generic count display
 * - EmptyState: Generic empty collection display
 * - InputBase: Basic input primitive (read-only, clickable for directory browsing)
 *
 * This demonstrates proper "write once, use everywhere" philosophy where:
 * - Atomic primitives handle single responsibilities
 * - Composed components orchestrate business logic
 * - Each primitive is reusable across different contexts
 */

import React, { useCallback, useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { SelectBase } from '../../primitives';
import { AddButton, EmptyState, FieldButton } from '../shared';
import { useTouchDevice } from '../../../../utils/touchDetection';
import { Modal } from '../../../ui';
import { FieldRegistry } from '../../FieldRegistry';

/**
 * SortableDirectoryItem - Directory item with drag and drop support
 * Handles reordering controls when enabled
 */
const SortableDirectoryItem = React.memo(
    ({
        id,
        index,
        directory,
        isLastItem,
        itemId,
        canMoveUp,
        canMoveDown,
        canRemoveDirectory,
        enableReordering,
        onMoveUp,
        onMoveDown,
        onRemove,
        onBrowseClick,
        onPathChange,
        disabled,
        invalid,
        placeholder,
        label,
        baseId,
        // Mode selection props
        mode,
        modeOptions,
        onModeChange,
        // Priority-order display (opt-in via field.priorityOrder)
        showPriority,
        priorityLabel,
        priorityHighest,
    }) => {
        const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
            useSortable({ id });

        const style = {
            transform: CSS.Transform.toString(transform),
            transition,
            opacity: isDragging ? 0.5 : 1,
        };

        const isTouch = useTouchDevice();

        const inputBlock = (
            <div
                className={`flex ${modeOptions ? 'flex-col gap-2 md:flex-row md:gap-3' : ''} flex-1 min-w-0`}
            >
                {/* Flat mono path (mock style) — borderless input inside the row's
                    inset container; the row border highlights on focus-within. */}
                <input
                    id={itemId}
                    type="text"
                    name={`${baseId}-${index}`}
                    value={directory || ''}
                    placeholder={placeholder}
                    disabled={disabled}
                    onChange={e => onPathChange(index, e.target.value)}
                    aria-label={`${label} ${index + 1}`}
                    aria-invalid={invalid || undefined}
                    className={`flex-1 min-w-0 bg-transparent border-0 outline-none p-0 font-mono text-[12.5px] text-fg-muted placeholder:text-fg-dim disabled:opacity-60 ${
                        modeOptions ? 'md:min-w-30' : ''
                    }`}
                />

                {/* Mode selection - only show if modeOptions provided */}
                {modeOptions && (
                    <SelectBase
                        id={`${itemId}-mode`}
                        name={`${baseId}-mode-${index}`}
                        value={mode || ''}
                        onChange={e => onModeChange?.(index, e.target.value)}
                        disabled={disabled}
                        invalid={invalid}
                        options={modeOptions}
                        placeholder="Select mode..."
                        className="flex-1"
                        aria-label={`Mode for ${label} ${index + 1}`}
                    />
                )}
            </div>
        );

        const browseButton = (
            <button
                type="button"
                onClick={() => onBrowseClick(index)}
                disabled={disabled}
                aria-label={`Browse for ${label} ${index + 1}`}
                className="shrink-0 flex items-center justify-center w-7 h-7 rounded-[7px] border border-border bg-transparent text-fg-subtle transition-colors hover:text-fg hover:border-border-light disabled:opacity-50 disabled:cursor-not-allowed"
            >
                <span className="material-symbols-outlined text-[15px]">folder_open</span>
            </button>
        );

        const moveUpButton = enableReordering && isTouch && (
            <FieldButton
                onClick={() => onMoveUp && onMoveUp(index)}
                disabled={!canMoveUp}
                ariaLabel={`Move ${directory || 'directory'} up`}
                className="flex-shrink-0"
            >
                <span className="material-symbols-outlined text-base">keyboard_arrow_up</span>
            </FieldButton>
        );

        const moveDownButton = enableReordering && isTouch && (
            <FieldButton
                onClick={() => onMoveDown && onMoveDown(index)}
                disabled={!canMoveDown}
                ariaLabel={`Move ${directory || 'directory'} down`}
                className="flex-shrink-0"
            >
                <span className="material-symbols-outlined text-base">keyboard_arrow_down</span>
            </FieldButton>
        );

        const removeButton = (
            <button
                type="button"
                onClick={() => onRemove(index)}
                disabled={!canRemoveDirectory}
                aria-label={`Remove ${label} ${index + 1}`}
                title={
                    isLastItem
                        ? 'Cannot remove the last directory entry'
                        : `Remove directory ${index + 1}`
                }
                className="shrink-0 flex items-center justify-center w-7 h-7 rounded-[7px] border border-border bg-transparent text-fg-subtle transition-colors hover:text-error hover:border-error/50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
                <span className="material-symbols-outlined text-[15px]">close</span>
            </button>
        );

        // Touch devices: stack input + browse on the top row,
        // reorder/remove controls right-aligned on a second row.
        // Keeps the path readable on narrow viewports instead of squeezing
        // it between four square buttons.
        if (isTouch) {
            return (
                <div
                    className="flex flex-col gap-2 px-[13px] py-2.5 rounded-[9px] bg-surface-inset border border-border focus-within:border-primary transition-colors"
                    ref={setNodeRef}
                    style={style}
                >
                    <div className="flex gap-2 items-stretch">
                        {inputBlock}
                        {browseButton}
                    </div>
                    <div className="flex justify-end gap-2">
                        {moveUpButton}
                        {moveDownButton}
                        {removeButton}
                    </div>
                </div>
            );
        }

        return (
            <div
                className="flex items-center gap-3 px-[13px] py-2.5 rounded-[9px] bg-surface-inset border border-border transition-colors focus-within:border-primary"
                ref={setNodeRef}
                style={style}
            >
                {/* Drag handle (left) — muted dots like the mock */}
                {enableReordering && (
                    <div
                        className="flex items-center justify-center shrink-0 text-fg-faint cursor-grab hover:text-fg-muted transition-colors"
                        {...attributes}
                        {...listeners}
                    >
                        <span className="material-symbols-outlined text-xl">drag_indicator</span>
                    </div>
                )}

                {showPriority && priorityLabel && (
                    <span
                        className={`flex-none self-center font-mono text-[10px] font-semibold px-2 py-0.5 rounded-[5px] whitespace-nowrap ${
                            priorityHighest
                                ? 'bg-success/15 text-success'
                                : 'bg-surface-elevated text-fg-muted'
                        }`}
                    >
                        {priorityLabel}
                    </span>
                )}

                {inputBlock}
                {browseButton}
                {removeButton}
            </div>
        );
    }
);

SortableDirectoryItem.displayName = 'SortableDirectoryItem';

/**
 * DirectoryItem - Regular directory item without drag and drop
 * For use in non-sortable directory lists
 */
const DirectoryItem = React.memo(
    ({
        index,
        directory,
        isLastItem,
        itemId,
        canRemoveDirectory,
        onRemove,
        onBrowseClick,
        onPathChange,
        disabled,
        invalid,
        placeholder,
        label,
        baseId,
        // Mode selection props
        mode,
        modeOptions,
        onModeChange,
    }) => {
        const isTouch = useTouchDevice();

        const inputBlock = (
            <div
                className={`flex ${modeOptions ? 'flex-col gap-2 md:flex-row md:gap-3' : ''} flex-1 min-w-0`}
            >
                {/* Flat mono path (mock style) — borderless input inside the row's
                    inset container; the row border highlights on focus-within. */}
                <input
                    id={itemId}
                    type="text"
                    name={`${baseId}-${index}`}
                    value={directory || ''}
                    placeholder={placeholder}
                    disabled={disabled}
                    onChange={e => onPathChange(index, e.target.value)}
                    aria-label={`${label} ${index + 1}`}
                    aria-invalid={invalid || undefined}
                    className={`flex-1 min-w-0 bg-transparent border-0 outline-none p-0 font-mono text-[12.5px] text-fg-muted placeholder:text-fg-dim disabled:opacity-60 ${
                        modeOptions ? 'md:min-w-30' : ''
                    }`}
                />

                {/* Mode selection - only show if modeOptions provided */}
                {modeOptions && (
                    <SelectBase
                        id={`${itemId}-mode`}
                        name={`${baseId}-mode-${index}`}
                        value={mode || ''}
                        onChange={e => onModeChange?.(index, e.target.value)}
                        disabled={disabled}
                        invalid={invalid}
                        options={modeOptions}
                        placeholder="Select mode..."
                        className="flex-1"
                        aria-label={`Mode for ${label} ${index + 1}`}
                    />
                )}
            </div>
        );

        const browseButton = (
            <button
                type="button"
                onClick={() => onBrowseClick(index)}
                disabled={disabled}
                aria-label={`Browse for ${label} ${index + 1}`}
                className="shrink-0 flex items-center justify-center w-7 h-7 rounded-[7px] border border-border bg-transparent text-fg-subtle transition-colors hover:text-fg hover:border-border-light disabled:opacity-50 disabled:cursor-not-allowed"
            >
                <span className="material-symbols-outlined text-[15px]">folder_open</span>
            </button>
        );

        const removeButton = (
            <button
                type="button"
                onClick={() => onRemove(index)}
                disabled={!canRemoveDirectory}
                aria-label={`Remove ${label} ${index + 1}`}
                title={
                    isLastItem
                        ? 'Cannot remove the last directory entry'
                        : `Remove directory ${index + 1}`
                }
                className="shrink-0 flex items-center justify-center w-7 h-7 rounded-[7px] border border-border bg-transparent text-fg-subtle transition-colors hover:text-error hover:border-error/50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
                <span className="material-symbols-outlined text-[15px]">close</span>
            </button>
        );

        if (isTouch) {
            return (
                <div className="flex flex-col gap-2 px-[13px] py-2.5 rounded-[9px] bg-surface-inset border border-border focus-within:border-primary transition-colors">
                    <div className="flex gap-2 items-stretch">
                        {inputBlock}
                        {browseButton}
                    </div>
                    <div className="flex justify-end gap-2">{removeButton}</div>
                </div>
            );
        }

        return (
            <div className="flex items-center gap-3 px-[13px] py-2.5 rounded-[9px] bg-surface-inset border border-border transition-colors focus-within:border-primary">
                {inputBlock}
                {browseButton}
                {removeButton}
            </div>
        );
    }
);

DirectoryItem.displayName = 'DirectoryItem';

/**
 * DirectoryArray component for managing multiple directories using atomic primitives
 *
 * @param {Object} props - Component props
 * @param {string[]} props.directories - Array of directory paths
 * @param {Function} props.onChange - Directories change handler: (directories: string[]) => void
 * @param {boolean} props.disabled - Disabled state for all controls
 * @param {boolean} props.invalid - Invalid/error state
 * @param {string} props.baseId - Base ID for generating input IDs
 * @param {string} props.label - Label text for ARIA descriptions
 * @param {number} props.minDirectories - Minimum number of directories required
 * @param {string} props.addButtonText - Text for add button
 * @param {string} props.removeButtonText - Text for remove button
 * @param {string} props.emptyMessage - Message shown when no directories
 * @param {string} props.emptySecondaryMessage - Secondary empty state message
 * @param {string} props.placeholder - Placeholder text for directory inputs
 * @param {string} props.className - Additional CSS classes
 * @param {boolean} props.enableReordering - Enable drag-drop reordering (optional)
 * @param {Function} props.onMoveUp - Move item up handler: (index: number) => void
 * @param {Function} props.onMoveDown - Move item down handler: (index: number) => void
 * @param {Object} props.dragHandleProps - Drag handle props for dnd-kit (optional)
 * @param {Array} props.modeOptions - Array of mode options for mode selection: [{value, label}] (optional)
 * @param {Array} props.modes - Array of mode values corresponding to directories (optional)
 * @param {Function} props.onModeChange - Mode change handler: (index: number, mode: string) => void (optional)
 */
export const DirectoryArray = React.memo(
    ({
        directories = [],
        onChange,
        disabled = false,
        invalid = false,
        baseId,
        label = 'directories',
        minDirectories = 0,
        addButtonText = 'Add Directory',
        removeButtonText = 'Remove',
        emptyMessage = 'No directories added yet.',
        emptySecondaryMessage = 'Click "Add Directory" to get started.',
        placeholder = 'Choose folder…',
        className = '',
        enableReordering = false,
        onMoveUp = null,
        onMoveDown = null,
        // Mode selection props
        modeOptions = null,
        modes = [],
        onModeChange = null,
        // Priority-order display (opt-in)
        showPriority = false,
        ...props
    }) => {
        const [modalOpen, setModalOpen] = useState(false);
        const [selectedIndex, setSelectedIndex] = useState(null);

        // Handle adding a new directory
        const handleAddDirectory = useCallback(() => {
            const newDirectories = [...directories, ''];
            onChange?.(newDirectories);
        }, [directories, onChange]);

        // Handle removing a directory at specific index
        const handleRemoveDirectory = useCallback(
            index => {
                if (directories.length <= minDirectories) return;

                const newDirectories = directories.filter((_, i) => i !== index);
                onChange?.(newDirectories);
            },
            [directories, minDirectories, onChange]
        );

        // Handle changing a directory at specific index
        const handleDirectoryChange = useCallback(
            (index, newPath) => {
                const newDirectories = [...directories];
                newDirectories[index] = newPath;
                onChange?.(newDirectories);
            },
            [directories, onChange]
        );

        // Handle clicking on directory input to open modal
        const handleDirectoryClick = useCallback(index => {
            setSelectedIndex(index);
            setModalOpen(true);
        }, []);

        const handlePickerChange = useCallback(
            newPath => {
                if (selectedIndex === null) return;
                handleDirectoryChange(selectedIndex, newPath);
                setModalOpen(false);
            },
            [handleDirectoryChange, selectedIndex]
        );

        const canAddDirectory = !disabled;
        const canRemoveDirectory = () => directories.length > minDirectories && !disabled;

        // Get dir_picker placeholder field component
        const DirPickerField = FieldRegistry.getField('dir_picker');
        const currentValue = selectedIndex !== null ? directories[selectedIndex] : '';

        return (
            <>
                <div
                    className={`flex flex-col gap-3 ${className}`.trim()}
                    role="group"
                    aria-label={`${label} list`}
                    {...props}
                >
                    {/* Directory Items */}
                    <div className="flex flex-col gap-4">
                        {directories.length === 0 ? (
                            <EmptyState
                                message={emptyMessage}
                                secondaryMessage={emptySecondaryMessage}
                                variant="subtle"
                                size="small"
                            >
                                <AddButton
                                    onClick={handleAddDirectory}
                                    disabled={!canAddDirectory}
                                    text={addButtonText}
                                    itemType="directory"
                                    disabledReason="Field is disabled"
                                />
                            </EmptyState>
                        ) : (
                            directories.map((directory, index) => {
                                const itemId = `${baseId}-dir-${index}`;
                                const isLastItem = directories.length === 1;

                                const canMoveUp = enableReordering && index > 0 && !disabled;
                                const canMoveDown =
                                    enableReordering && index < directories.length - 1 && !disabled;

                                // Get mode for this directory index
                                const itemMode = modes[index] || '';

                                // Priority badge: bottom of the list wins.
                                const isHighest = index === directories.length - 1;
                                const priorityLabel = showPriority
                                    ? `P${index + 1}${
                                          isHighest ? ' · wins' : index === 0 ? ' · base' : ''
                                      }`
                                    : null;

                                // Use SortableDirectoryItem for drag and drop, regular DirectoryItem otherwise
                                if (enableReordering) {
                                    return (
                                        <SortableDirectoryItem
                                            key={index}
                                            id={index.toString()}
                                            index={index}
                                            directory={directory}
                                            isLastItem={isLastItem}
                                            itemId={itemId}
                                            canMoveUp={canMoveUp}
                                            canMoveDown={canMoveDown}
                                            canRemoveDirectory={canRemoveDirectory()}
                                            enableReordering={enableReordering}
                                            onMoveUp={onMoveUp}
                                            onMoveDown={onMoveDown}
                                            onRemove={handleRemoveDirectory}
                                            onBrowseClick={handleDirectoryClick}
                                            onPathChange={handleDirectoryChange}
                                            disabled={disabled}
                                            invalid={invalid}
                                            placeholder={placeholder}
                                            label={label}
                                            baseId={baseId}
                                            removeButtonText={removeButtonText}
                                            // Mode selection props
                                            mode={itemMode}
                                            modeOptions={modeOptions}
                                            onModeChange={onModeChange}
                                            // Priority display
                                            showPriority={showPriority}
                                            priorityLabel={priorityLabel}
                                            priorityHighest={isHighest}
                                        />
                                    );
                                } else {
                                    return (
                                        <DirectoryItem
                                            key={index}
                                            index={index}
                                            directory={directory}
                                            isLastItem={isLastItem}
                                            itemId={itemId}
                                            canRemoveDirectory={canRemoveDirectory()}
                                            onRemove={handleRemoveDirectory}
                                            onBrowseClick={handleDirectoryClick}
                                            onPathChange={handleDirectoryChange}
                                            disabled={disabled}
                                            invalid={invalid}
                                            placeholder={placeholder}
                                            label={label}
                                            baseId={baseId}
                                            removeButtonText={removeButtonText}
                                            // Mode selection props
                                            mode={itemMode}
                                            modeOptions={modeOptions}
                                            onModeChange={onModeChange}
                                        />
                                    );
                                }
                            })
                        )}
                    </div>

                    {/* Add Button & Counter (only show if we have items or can add) */}
                    {directories.length > 0 && (
                        <div className="flex items-center gap-3">
                            <AddButton
                                onClick={handleAddDirectory}
                                disabled={!canAddDirectory}
                                text={addButtonText}
                                itemType="directory"
                                disabledReason="Field is disabled"
                            />
                        </div>
                    )}
                </div>

                {/* Directory Browser Modal — bottom-sheet variant slides up
                    from the bottom on mobile so the picker feels like a
                    native folder picker rather than a centered dialog */}
                <Modal
                    isOpen={modalOpen}
                    onClose={() => setModalOpen(false)}
                    size="large"
                    variant="bottom-sheet"
                >
                    <Modal.Header>Select Directory</Modal.Header>
                    <Modal.Body>
                        <div className="flex flex-col gap-4">
                            {DirPickerField && (
                                <DirPickerField
                                    field={{
                                        key: 'directory_browser',
                                        label: 'Directory Browser',
                                        type: 'dir_picker',
                                        description: 'Browse and select a directory',
                                    }}
                                    value={currentValue}
                                    onChange={handlePickerChange}
                                />
                            )}
                        </div>
                    </Modal.Body>
                    <Modal.Footer>
                        <button
                            onClick={() => setModalOpen(false)}
                            className="px-4 py-2 bg-surface-alt text-fg rounded-lg hover:bg-surface-hover transition-colors min-h-11"
                        >
                            Close
                        </button>
                    </Modal.Footer>
                </Modal>
            </>
        );
    }
);

DirectoryArray.displayName = 'DirectoryArray';

export default DirectoryArray;
