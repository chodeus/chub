/**
 * BulkSelectList - presentational multi-select panel
 *
 * Collapsible panel with grouped checkbox rows and an "Add selected" button.
 * Backs both the GDrive preset bulk-add (Sync GDrive) and the configured-drive
 * bulk-add (Poster Renamerr). Owns only its selection state; the container
 * supplies the grouped items and handles what "add" actually does.
 */

import React, { useState, useCallback, useMemo } from 'react';
import { CheckboxBase } from '../primitives';

const PRIMARY_BUTTON_CLASSES =
    'min-h-11 min-w-11 inline-flex items-center justify-center px-4 py-3 rounded-lg text-sm font-medium transition-colors cursor-pointer border bg-primary text-white border-primary hover:bg-primary-hover focus:outline-2 focus:outline-primary focus:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed w-full md:w-auto md:min-w-25';

/**
 * @param {Object} props
 * @param {string} props.title - Collapsed-header label.
 * @param {boolean} props.loading - Show a loading row.
 * @param {Array} props.groups - [{ key, label, items: [{ value, label, sublabel, disabled }] }]
 * @param {React.ReactNode} props.headerSlot - Rendered above the list (e.g. global-dir input).
 * @param {boolean} props.canAdd - Extra gate beyond having a selection (default true).
 * @param {string} props.addDisabledReason - Hint shown when canAdd is false.
 * @param {(count:number)=>string} props.addButtonText - Builds the add-button label.
 * @param {(selected:string[])=>void} props.onAdd - Called with selected values; selection is cleared after.
 * @param {string} props.emptyMessage - Shown when there are no selectable items.
 * @param {boolean} props.disabled - Disable the whole panel.
 */
export const BulkSelectList = React.memo(
    ({
        title = 'Add from list',
        loading = false,
        groups = [],
        headerSlot = null,
        canAdd = true,
        addDisabledReason = null,
        addButtonText = count => `Add ${count} selected`,
        onAdd,
        emptyMessage = 'Nothing available to add.',
        disabled = false,
    }) => {
        const [open, setOpen] = useState(false);
        const [selected, setSelected] = useState(() => new Set());

        const toggleItem = useCallback(value => {
            setSelected(prev => {
                const next = new Set(prev);
                if (next.has(value)) next.delete(value);
                else next.add(value);
                return next;
            });
        }, []);

        // Enabled (not already-added) values per group, for the select-all box.
        const enabledByGroup = useMemo(() => {
            const map = {};
            groups.forEach(g => {
                map[g.key] = (g.items || []).filter(i => !i.disabled).map(i => i.value);
            });
            return map;
        }, [groups]);

        const toggleGroup = useCallback(
            groupKey => {
                const values = enabledByGroup[groupKey] || [];
                setSelected(prev => {
                    const next = new Set(prev);
                    const allOn = values.length > 0 && values.every(v => next.has(v));
                    if (allOn) values.forEach(v => next.delete(v));
                    else values.forEach(v => next.add(v));
                    return next;
                });
            },
            [enabledByGroup]
        );

        const handleAdd = useCallback(() => {
            if (!onAdd || selected.size === 0) return;
            onAdd([...selected]);
            setSelected(new Set());
        }, [onAdd, selected]);

        const hasItems = groups.some(g => (g.items || []).length > 0);

        return (
            <div className="border border-border rounded-lg bg-surface-alt overflow-hidden">
                <button
                    type="button"
                    className="w-full flex items-center justify-between p-3 min-h-11 cursor-pointer text-sm font-medium text-primary hover:bg-surface-hover transition-colors"
                    onClick={() => setOpen(o => !o)}
                    aria-expanded={open}
                >
                    <span>{title}</span>
                    <span className="material-symbols-outlined text-base">
                        {open ? 'expand_less' : 'expand_more'}
                    </span>
                </button>

                {open && (
                    <div className="p-4 flex flex-col gap-4 border-t border-border">
                        {headerSlot}

                        {loading ? (
                            <div className="text-sm text-secondary">Loading…</div>
                        ) : !hasItems ? (
                            <div className="text-sm text-secondary">{emptyMessage}</div>
                        ) : (
                            groups
                                .filter(g => (g.items || []).length > 0)
                                .map(group => {
                                    const values = enabledByGroup[group.key] || [];
                                    const allOn =
                                        values.length > 0 && values.every(v => selected.has(v));
                                    return (
                                        <div key={group.key} className="flex flex-col gap-2">
                                            {group.label && (
                                                <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-secondary uppercase">
                                                    <CheckboxBase
                                                        id={`bulk-group-${group.key}`}
                                                        name={`bulk-group-${group.key}`}
                                                        checked={allOn}
                                                        disabled={disabled || values.length === 0}
                                                        onChange={() => toggleGroup(group.key)}
                                                    />
                                                    <span>{group.label}</span>
                                                </label>
                                            )}
                                            <div className="flex flex-col">
                                                {group.items.map(item => (
                                                    <label
                                                        key={item.value}
                                                        className={`flex items-center gap-3 p-2 rounded-lg ${
                                                            item.disabled
                                                                ? 'opacity-60'
                                                                : 'cursor-pointer hover:bg-surface-hover'
                                                        }`}
                                                    >
                                                        <CheckboxBase
                                                            id={`bulk-item-${item.value}`}
                                                            name={`bulk-item-${item.value}`}
                                                            checked={
                                                                item.disabled ||
                                                                selected.has(item.value)
                                                            }
                                                            disabled={disabled || item.disabled}
                                                            onChange={() => toggleItem(item.value)}
                                                        />
                                                        <span className="flex flex-col min-w-0">
                                                            <span className="text-sm text-primary truncate">
                                                                {item.label}
                                                                {item.disabled && (
                                                                    <span className="text-secondary">
                                                                        {' '}
                                                                        (Already added)
                                                                    </span>
                                                                )}
                                                            </span>
                                                            {item.sublabel && (
                                                                <span className="text-xs text-secondary truncate">
                                                                    {item.sublabel}
                                                                </span>
                                                            )}
                                                        </span>
                                                    </label>
                                                ))}
                                            </div>
                                        </div>
                                    );
                                })
                        )}

                        {addDisabledReason && !canAdd && (
                            <div className="text-xs text-secondary">{addDisabledReason}</div>
                        )}

                        <div className="flex justify-end">
                            <button
                                type="button"
                                className={PRIMARY_BUTTON_CLASSES}
                                onClick={handleAdd}
                                disabled={disabled || !canAdd || selected.size === 0}
                            >
                                {addButtonText(selected.size)}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        );
    }
);

BulkSelectList.displayName = 'BulkSelectList';

export default BulkSelectList;
