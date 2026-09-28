import React, { useState } from 'react';
import PropTypes from 'prop-types';

/** Label and count over a bar scaled to the largest count. `onSelect` turns each
 *  row into a toggle button; `maxItems` adds a show-all control. Rows keep caller order. */
export const BarList = ({ items, onSelect, activeLabel, maxItems, labelClassName = '' }) => {
    const [expanded, setExpanded] = useState(false);
    if (!items || items.length === 0) return null;

    const max = items.reduce((m, item) => Math.max(m, item.count ?? 0), 0) || 1;
    const collapsible = Boolean(maxItems) && items.length > maxItems;
    const shown = collapsible && !expanded ? items.slice(0, maxItems) : items;
    const interactive = typeof onSelect === 'function';

    return (
        <div>
            <div className="flex flex-col gap-3">
                {shown.map(({ label, count, pct, color }, i) => {
                    const value = count ?? 0;
                    const active = activeLabel === label;
                    const row = (
                        <>
                            <div className="flex justify-between gap-3 text-sm mb-1">
                                <span
                                    className={`min-w-0 truncate ${active ? 'text-accent' : 'text-fg'} ${labelClassName}`}
                                    title={typeof label === 'string' ? label : undefined}
                                >
                                    {label}
                                    {interactive && <span className="text-fg-subtle"> ›</span>}
                                </span>
                                <span className="shrink-0 font-mono text-xs text-fg-subtle">
                                    {value.toLocaleString()}
                                    {pct != null && ` · ${pct.toFixed(1)}%`}
                                </span>
                            </div>
                            <div className="h-2 bg-border rounded-full overflow-hidden">
                                <div
                                    className="h-full rounded-full"
                                    style={{
                                        width: `${(value / max) * 100}%`,
                                        background: color || 'var(--accent)',
                                    }}
                                />
                            </div>
                        </>
                    );
                    return interactive ? (
                        <button
                            key={`${i}:${label}`}
                            type="button"
                            aria-pressed={active}
                            onClick={() => onSelect(label)}
                            className="block w-full text-left"
                        >
                            {row}
                        </button>
                    ) : (
                        <div key={`${i}:${label}`}>{row}</div>
                    );
                })}
            </div>
            {collapsible && (
                <button
                    type="button"
                    className="touch-expand mt-3 text-sm text-accent hover:underline"
                    onClick={() => setExpanded(e => !e)}
                >
                    {expanded ? 'Show less' : `Show all ${items.length}`}
                </button>
            )}
        </div>
    );
};

BarList.propTypes = {
    items: PropTypes.arrayOf(
        PropTypes.shape({
            label: PropTypes.string.isRequired,
            count: PropTypes.number,
            // Share of the whole, shown after the count when present.
            pct: PropTypes.number,
            color: PropTypes.string,
        })
    ),
    onSelect: PropTypes.func,
    activeLabel: PropTypes.string,
    maxItems: PropTypes.number,
    labelClassName: PropTypes.string,
};

export default BarList;
