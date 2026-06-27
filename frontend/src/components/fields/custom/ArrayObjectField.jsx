import { useState, useCallback } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription } from '../primitives';
import { RemoveButton, AddButton, ColorSwatches } from '../features/shared';
import { FieldRegistry } from '../FieldRegistry';
import { BulkPresetPicker } from './BulkPresetPicker';
import {
    shouldShowField,
    generateInstanceOptions,
    getInstanceType,
    resolveTypeAwareField,
} from '../../../utils/forms/conditionalFields';
import { useInstancesData } from '../../../hooks/useInstancesData';
import { scheduleToHuman } from '../../../utils/schedule';
import Toggle from '../../ui/Toggle.jsx';
import SegmentedControl from '../../ui/SegmentedControl.jsx';
import { Modal } from '../../ui';

/**
 * Unified ArrayObjectField - Handles dynamic array of objects with configurable schemas
 * Uses accordion-style expansion for mobile-first design without modal dependency
 * @param {Object} props - Component props
 * @param {Object} props.field - Field configuration with schema for object fields
 * @param {Array} props.value - Array of objects
 * @param {Function} props.onChange - Value change handler
 * @param {boolean} props.disabled - Field disabled state
 * @param {boolean} props.highlightInvalid - Show validation errors
 * @param {string} props.errorMessage - Error message to display
 */
export const ArrayObjectField = ({
    field,
    value = [],
    onChange,
    disabled = false,
    highlightInvalid = false,
    errorMessage,
}) => {
    const [expandedIndex, setExpandedIndex] = useState(null);
    const [editingData, setEditingData] = useState({});
    // Which gdrive-table row has its folder-picker modal open (bespoke gdrive view).
    const [gdrivePickerRow, setGdrivePickerRow] = useState(null);

    // Load instances data for conditional field evaluation and dynamic dropdowns
    const { instancesData } = useInstancesData();

    const inputId = `field-${field.key}`;

    // Get display template for this field type
    const displayTemplate = getDisplayTemplate(field.displayType || field.type);

    const buildDefaultItem = useCallback(() => {
        const defaults = {};
        (field.fields || []).forEach(subField => {
            const defaultValue =
                subField.defaultValue !== undefined ? subField.defaultValue : subField.default;
            if (defaultValue !== undefined) {
                defaults[subField.key] =
                    Array.isArray(defaultValue) || typeof defaultValue === 'object'
                        ? structuredClone(defaultValue)
                        : defaultValue;
            }
        });
        return defaults;
    }, [field.fields]);

    const handleAdd = useCallback(() => {
        const newIndex = value.length;
        setExpandedIndex(newIndex);
        setEditingData(buildDefaultItem());
    }, [value.length, buildDefaultItem]);

    const handleEdit = useCallback(
        index => {
            // Toggle behavior: if clicking on already expanded item, close it
            if (expandedIndex === index) {
                setExpandedIndex(null);
                setEditingData({});
            } else {
                setExpandedIndex(index);
                setEditingData({ ...value[index] });
            }
        },
        [value, expandedIndex]
    );

    const handleSave = useCallback(() => {
        if (expandedIndex === null) return;

        const newArray = [...value];
        if (expandedIndex >= newArray.length) {
            // Adding new item
            newArray.push(editingData);
        } else {
            // Editing existing item
            newArray[expandedIndex] = editingData;
        }

        onChange(newArray);
        setExpandedIndex(null);
        setEditingData({});
    }, [expandedIndex, editingData, value, onChange]);

    const handleCancel = useCallback(() => {
        setExpandedIndex(null);
        setEditingData({});
    }, []);

    const handleRemove = useCallback(
        index => {
            const newArray = value.filter((_, i) => i !== index);
            onChange(newArray);
            if (expandedIndex === index) {
                setExpandedIndex(null);
                setEditingData({});
            }
        },
        [value, onChange, expandedIndex]
    );

    const handleFieldChange = useCallback((fieldKey, fieldValue) => {
        setEditingData(prev => ({
            ...prev,
            [fieldKey]: fieldValue,
        }));
    }, []);

    // Handle preset selection for fields that support multi-field updates
    const handlePresetSelected = useCallback(presetFieldUpdates => {
        setEditingData(prev => ({
            ...prev,
            ...presetFieldUpdates,
        }));
    }, []);

    const renderDisplayItem = (item, index) => {
        const { primary, secondary, badge } = displayTemplate.display(item);
        const isExpanded = expandedIndex === index;

        return (
            <div key={index} className="border-b border-border last:border-b-0">
                <div
                    className="flex items-center justify-between p-3 min-h-11 cursor-pointer transition-colors hover:bg-surface-hover focus:bg-surface-hover focus:outline-2 focus:outline-primary"
                    style={{ outlineOffset: '-2px' }}
                    onClick={() => handleEdit(index)}
                    tabIndex={0}
                    onKeyDown={e => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleEdit(index);
                        }
                    }}
                >
                    <div className="flex-1 flex flex-col gap-1 md:flex-row md:items-center md:gap-4 min-w-0">
                        <div className="font-medium text-fg text-sm truncate">{primary}</div>
                        {secondary &&
                            (Array.isArray(secondary) ? (
                                <div className="flex flex-wrap gap-1.5">
                                    {secondary
                                        .filter(s => s != null && s !== '')
                                        .map((seg, i) => (
                                            <span
                                                key={i}
                                                className="inline-flex items-center px-1.5 py-0.5 rounded bg-surface-alt text-xs text-fg-muted"
                                            >
                                                {seg}
                                            </span>
                                        ))}
                                </div>
                            ) : (
                                <div className="text-xs text-fg-muted truncate">{secondary}</div>
                            ))}
                        {badge && (
                            <div className="inline-flex items-center px-2 py-0.5 bg-primary/15 text-brand-primary rounded text-xs font-medium whitespace-nowrap self-start md:ml-auto md:flex-shrink-0">
                                {/* Show color swatches for items with colors array */}
                                {item.colors && Array.isArray(item.colors) ? (
                                    <ColorSwatches colors={item.colors} size="sm" maxDisplay={3} />
                                ) : (
                                    badge
                                )}
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-2 ml-3">
                        <RemoveButton
                            onClick={e => {
                                e.stopPropagation();
                                handleRemove(index);
                            }}
                            itemName={`${displayTemplate.itemName} ${index + 1}`}
                            disabled={disabled}
                        />
                    </div>
                </div>

                {/* Render edit form directly below this item if expanded */}
                {isExpanded && renderEditForm()}
            </div>
        );
    };

    const renderEditForm = () => {
        if (expandedIndex === null) return null;

        const isEditing = expandedIndex < value.length;
        const title = isEditing
            ? `Edit ${displayTemplate.itemName} ${expandedIndex + 1}`
            : `Add New ${displayTemplate.itemName}`;

        // Prepare API data for conditional field evaluation
        const apiData = {
            instances: instancesData,
        };

        return (
            <div className="border border-border rounded-lg bg-surface-alt overflow-hidden animate-slide-down">
                <div className="p-4 border-b border-border bg-surface">
                    <h3 className="m-0 text-base font-semibold text-fg">{title}</h3>
                </div>

                <div className="p-4 flex flex-col gap-4">
                    {field.fields
                        .filter(subField => shouldShowField(subField, editingData, apiData))
                        .map(subField => {
                            const FieldComponent = getFieldComponent(subField.type);

                            // Additional props for specific field types
                            const additionalProps = {};
                            if (subField.type === 'presets') {
                                additionalProps.onPresetSelected = handlePresetSelected;
                                // PresetsField looks up moduleConfig[moduleConfigKey]
                                // (e.g. moduleConfig.gdrive_list) to find entries
                                // already added. Wrap the array under the parent
                                // field key so that lookup hits.
                                additionalProps.moduleConfig = { [field.key]: value };
                            }

                            // Enhanced dropdown with API integration
                            let enhancedField = subField;
                            if (subField.options_source === 'api_instances') {
                                const instanceOptions = generateInstanceOptions(
                                    apiData?.instances,
                                    subField.options_filter,
                                    false // Don't include placeholder in options array since we set it on field
                                );
                                // Create enhanced field with dynamic options and placeholder
                                enhancedField = {
                                    ...subField,
                                    options: instanceOptions,
                                    placeholder: '— Select instance... —', // Override DropdownField default
                                };
                            }

                            // Resolve instance-type-aware labels/description so a
                            // shared setting speaks the right vocabulary (e.g.
                            // Sonarr "Series/Season" vs Lidarr "Artist/Album").
                            const typeField = subField.typeField || 'instance';
                            const instanceType = getInstanceType(
                                editingData[typeField],
                                apiData.instances
                            );
                            enhancedField = resolveTypeAwareField(enhancedField, instanceType);

                            return (
                                <div key={subField.key}>
                                    <FieldComponent
                                        field={enhancedField}
                                        value={
                                            editingData[subField.key] ??
                                            subField.defaultValue ??
                                            subField.default ??
                                            ''
                                        }
                                        onChange={value => handleFieldChange(subField.key, value)}
                                        disabled={disabled}
                                        {...additionalProps}
                                    />
                                </div>
                            );
                        })}
                </div>

                <div className="flex gap-3 p-4 border-t border-border bg-surface justify-end flex-col-reverse md:flex-row">
                    <button
                        type="button"
                        className="min-h-11 min-w-11 inline-flex items-center justify-center px-4 py-3 rounded-lg text-sm font-medium transition-colors cursor-pointer border bg-surface text-fg border-border hover:bg-surface-hover focus:outline-2 focus:outline-primary focus:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed w-full md:w-auto md:min-w-25"
                        onClick={handleCancel}
                        disabled={disabled}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        className="min-h-11 min-w-11 inline-flex items-center justify-center px-4 py-3 rounded-lg text-sm font-medium transition-colors cursor-pointer border bg-primary text-white border-primary hover:bg-primary-hover focus:outline-2 focus:outline-primary focus:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed w-full md:w-auto md:min-w-25"
                        onClick={handleSave}
                        disabled={disabled}
                    >
                        {isEditing ? 'Save Changes' : `Add ${displayTemplate.itemName}`}
                    </button>
                </div>
            </div>
        );
    };

    // ── Always-expanded card mode (opt-in via field.alwaysExpanded) ──────────
    // Each item is an open card whose fields edit the item in place — no
    // draft/Save round-trip. Used by the per-instance / mapping module configs
    // whose mocks show every field at once.
    const handleItemFieldChange = useCallback(
        (index, fieldKey, fieldValue) => {
            onChange(value.map((it, i) => (i === index ? { ...it, [fieldKey]: fieldValue } : it)));
        },
        [value, onChange]
    );

    const handleAddExpanded = useCallback(() => {
        onChange([...value, buildDefaultItem()]);
    }, [value, onChange, buildDefaultItem]);

    const renderItemFields = (item, index) => {
        const apiData = { instances: instancesData };
        return field.fields
            .filter(subField => shouldShowField(subField, item, apiData))
            .map(subField => {
                const FieldComponent = getFieldComponent(subField.type);
                const additionalProps = {};
                if (subField.type === 'presets') {
                    additionalProps.moduleConfig = { [field.key]: value };
                }
                let enhancedField = subField;
                if (subField.options_source === 'api_instances') {
                    enhancedField = {
                        ...subField,
                        options: generateInstanceOptions(
                            apiData?.instances,
                            subField.options_filter,
                            false
                        ),
                        placeholder: '— Select instance... —',
                    };
                }
                const typeField = subField.typeField || 'instance';
                const instanceType = getInstanceType(item[typeField], apiData.instances);
                enhancedField = resolveTypeAwareField(enhancedField, instanceType);
                return (
                    <div key={subField.key}>
                        <FieldComponent
                            field={enhancedField}
                            value={
                                item[subField.key] ??
                                subField.defaultValue ??
                                subField.default ??
                                ''
                            }
                            onChange={val => handleItemFieldChange(index, subField.key, val)}
                            disabled={disabled}
                            {...additionalProps}
                        />
                    </div>
                );
            });
    };

    const renderExpandedCard = (item, index) => {
        const { primary, badge } = displayTemplate.display(item);
        return (
            <div key={index} className="bg-surface border border-border rounded-xl overflow-hidden">
                <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-surface-inset">
                    <div className="min-w-0 flex-1">
                        <div className="font-semibold text-sm text-fg truncate">{primary}</div>
                    </div>
                    {badge && (
                        <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-surface text-fg-muted border border-border whitespace-nowrap">
                            {badge}
                        </span>
                    )}
                    <RemoveButton
                        onClick={() => handleRemove(index)}
                        itemName={`${displayTemplate.itemName} ${index + 1}`}
                        disabled={disabled}
                    />
                </div>
                <div className="p-4 flex flex-col gap-4">{renderItemFields(item, index)}</div>
            </div>
        );
    };

    // Bespoke Upgradinatorr profile card — matches the design mock's compact
    // layout (inline name + schedule readout + Enabled + remove in the header,
    // a labelled grid of the core fields, the rich schedule picker, and the
    // unattended footer). Reuses handleItemFieldChange so emit shapes are intact.
    const renderUpgradinatorrCard = (item, index) => {
        const apiData = { instances: instancesData };
        const set = (k, v) => handleItemFieldChange(index, k, v);
        const byKey = k => (field.fields || []).find(f => f.key === k);
        const enabled = item.enabled !== false;
        const instanceOptions = generateInstanceOptions(
            apiData.instances,
            byKey('instance')?.options_filter,
            false
        );
        const instanceType = getInstanceType(item.instance, apiData.instances);
        const ScheduleComp = getFieldComponent('schedule');
        const schedHuman = item.schedule ? scheduleToHuman(item.schedule) : 'Main schedule only';
        const showCountMode = shouldShowField(byKey('count_mode'), item, apiData);
        const showThreshold = shouldShowField(byKey('season_monitored_threshold'), item, apiData);
        const countModeOpts = (byKey('count_mode')?.options || []).map(o => ({
            value: o.value,
            label: o.labelByType?.[instanceType] || o.labelByType?.default || o.value,
        }));
        const lbl = 'font-mono text-[10px] tracking-[0.8px] text-fg-subtle';
        const ctrl =
            'h-9 px-2.5 rounded-md bg-surface-inset border border-border text-fg text-sm outline-none focus:border-primary w-full';
        return (
            <div
                key={index}
                className={`bg-surface border border-border rounded-xl overflow-hidden ${enabled ? '' : 'opacity-60'}`}
            >
                <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-surface-inset">
                    <input
                        value={item.label || ''}
                        onChange={e => set('label', e.target.value)}
                        placeholder="Profile name"
                        disabled={disabled}
                        className="font-display font-semibold text-sm text-fg bg-transparent border-0 outline-none min-w-0 max-w-[240px] flex-1"
                    />
                    <span
                        className={`font-mono text-[11px] shrink-0 ${enabled ? 'text-accent' : 'text-fg-subtle'}`}
                    >
                        {schedHuman}
                    </span>
                    <label className="ml-auto flex items-center gap-2 text-[12.5px] text-fg-muted shrink-0">
                        Enabled
                        <Toggle
                            label="Enabled"
                            checked={enabled}
                            disabled={disabled}
                            onChange={v => set('enabled', v)}
                        />
                    </label>
                    <RemoveButton
                        onClick={() => handleRemove(index)}
                        itemName={`profile ${index + 1}`}
                        disabled={disabled}
                    />
                </div>
                <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    <label className="flex flex-col gap-1.5">
                        <span className={lbl}>INSTANCE</span>
                        <select
                            value={item.instance || ''}
                            onChange={e => set('instance', e.target.value)}
                            disabled={disabled}
                            className={ctrl}
                        >
                            <option value="">— Select —</option>
                            {instanceOptions.map(o => (
                                <option key={o.value} value={o.value}>
                                    {o.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="flex flex-col gap-1.5">
                        <span className={lbl}>COUNT / RUN</span>
                        <input
                            type="number"
                            value={item.count ?? ''}
                            onChange={e =>
                                set('count', e.target.value === '' ? '' : Number(e.target.value))
                            }
                            disabled={disabled}
                            className={`${ctrl} font-mono`}
                        />
                    </label>
                    {showCountMode && (
                        <label className="flex flex-col gap-1.5">
                            <span className={lbl}>COUNT MODE</span>
                            <select
                                value={item.count_mode || 'series_artist'}
                                onChange={e => set('count_mode', e.target.value)}
                                disabled={disabled}
                                className={ctrl}
                            >
                                {countModeOpts.map(o => (
                                    <option key={o.value} value={o.value}>
                                        {o.label}
                                    </option>
                                ))}
                            </select>
                        </label>
                    )}
                    <label className="flex flex-col gap-1.5">
                        <span className={lbl}>TAG NAME</span>
                        <input
                            type="text"
                            value={item.tag_name || ''}
                            onChange={e => set('tag_name', e.target.value)}
                            placeholder="checked"
                            disabled={disabled}
                            className={`${ctrl} font-mono`}
                        />
                    </label>
                    <label className="flex flex-col gap-1.5">
                        <span className={lbl}>IGNORE TAG</span>
                        <input
                            type="text"
                            value={item.ignore_tag || ''}
                            onChange={e => set('ignore_tag', e.target.value)}
                            placeholder="ignore"
                            disabled={disabled}
                            className={`${ctrl} font-mono`}
                        />
                    </label>
                    {showThreshold && (
                        <label className="flex flex-col gap-1.5">
                            <span className={lbl}>SEASON MONITORED %</span>
                            <input
                                type="number"
                                step="0.01"
                                value={item.season_monitored_threshold ?? ''}
                                onChange={e =>
                                    set(
                                        'season_monitored_threshold',
                                        e.target.value === '' ? '' : Number(e.target.value)
                                    )
                                }
                                disabled={disabled}
                                className={`${ctrl} font-mono`}
                            />
                        </label>
                    )}
                    <label className="flex flex-col gap-1.5 sm:col-span-2 lg:col-span-3">
                        <span className={lbl}>SEARCH MODE</span>
                        <div>
                            <SegmentedControl
                                size="sm"
                                options={[
                                    { value: 'upgrade', label: 'Upgrade' },
                                    { value: 'missing', label: 'Missing' },
                                    { value: 'cutoff', label: 'Cutoff' },
                                ]}
                                value={item.search_mode || 'upgrade'}
                                onChange={v => set('search_mode', v)}
                            />
                        </div>
                    </label>
                </div>
                <div className="px-4 pb-3">
                    <ScheduleComp
                        field={byKey('schedule')}
                        value={item.schedule}
                        onChange={v => set('schedule', v)}
                        disabled={disabled}
                    />
                </div>
                <div className="flex items-center gap-2.5 px-4 pb-4">
                    <Toggle
                        label="Auto reset"
                        checked={!!item.unattended}
                        disabled={disabled}
                        onChange={v => set('unattended', v)}
                    />
                    <span className="text-[12.5px] text-fg-muted">
                        Unattended — when every eligible item is tagged, clear the tag and start the
                        rotation again.
                    </span>
                </div>
            </div>
        );
    };

    // Bespoke Sync-GDrive drive table — matches the mock's compact rows
    // (NAME / FOLDER ID / LOCAL LOCATION + browse-only + remove) under column
    // headers. Location stays editable AND keeps the folder picker via a browse
    // button that opens the same dir_picker modal DirField uses.
    const renderGdriveTable = () => {
        const DirPickerField = FieldRegistry.getField('dir_picker');
        const cols = '1fr 1.3fr 1.2fr auto 32px';
        const head = 'font-mono text-[10px] tracking-[0.8px] text-fg-subtle';
        const cell =
            'h-9 px-2.5 rounded-md bg-surface-inset border border-border text-fg text-sm outline-none focus:border-primary w-full';
        return (
            <>
                {value.length > 0 ? (
                    <>
                        <div className="grid gap-3 px-2" style={{ gridTemplateColumns: cols }}>
                            <span className={head}>NAME</span>
                            <span className={head}>FOLDER ID</span>
                            <span className={head}>LOCAL LOCATION</span>
                            <span className={head}>BROWSE ONLY</span>
                            <span />
                        </div>
                        <div className="flex flex-col gap-2">
                            {value.map((item, index) => (
                                <div
                                    key={index}
                                    className="grid gap-3 items-center px-2 py-2 rounded-lg bg-surface border border-border"
                                    style={{ gridTemplateColumns: cols }}
                                >
                                    <input
                                        value={item.name || ''}
                                        onChange={e =>
                                            handleItemFieldChange(index, 'name', e.target.value)
                                        }
                                        placeholder="Name"
                                        disabled={disabled}
                                        className={cell}
                                    />
                                    <input
                                        value={item.id || ''}
                                        onChange={e =>
                                            handleItemFieldChange(index, 'id', e.target.value)
                                        }
                                        placeholder="Folder ID"
                                        disabled={disabled}
                                        className={`${cell} font-mono text-xs`}
                                    />
                                    <div className="flex items-center gap-1.5">
                                        <input
                                            value={item.location || ''}
                                            onChange={e =>
                                                handleItemFieldChange(
                                                    index,
                                                    'location',
                                                    e.target.value
                                                )
                                            }
                                            placeholder="/local/path"
                                            disabled={disabled}
                                            className={`${cell} font-mono text-xs`}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setGdrivePickerRow(index)}
                                            disabled={disabled}
                                            title="Browse folders"
                                            className="shrink-0 inline-flex items-center justify-center w-9 h-9 rounded-md bg-surface-inset border border-border text-fg-muted hover:border-primary"
                                        >
                                            <span className="material-symbols-outlined text-[18px]">
                                                folder_open
                                            </span>
                                        </button>
                                    </div>
                                    <div className="flex justify-center">
                                        <Toggle
                                            label="Browse only"
                                            checked={!!item.search_only}
                                            disabled={disabled}
                                            onChange={v =>
                                                handleItemFieldChange(index, 'search_only', v)
                                            }
                                        />
                                    </div>
                                    <RemoveButton
                                        onClick={() => handleRemove(index)}
                                        itemName={`drive ${index + 1}`}
                                        disabled={disabled}
                                    />
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <div className="p-8 text-center border border-dashed border-border rounded-lg bg-surface-alt">
                        <div className="text-sm text-fg-muted">No drive locations configured</div>
                    </div>
                )}
                <Modal
                    isOpen={gdrivePickerRow !== null}
                    onClose={() => setGdrivePickerRow(null)}
                    size="large"
                >
                    <Modal.Header>Select Directory</Modal.Header>
                    <Modal.Body>
                        {DirPickerField && (
                            <DirPickerField
                                field={{
                                    key: 'directory_browser',
                                    label: 'Directory Browser',
                                    type: 'dir_picker',
                                    description: 'Browse and select a directory',
                                }}
                                value={
                                    gdrivePickerRow !== null
                                        ? value[gdrivePickerRow]?.location || ''
                                        : ''
                                }
                                onChange={path => {
                                    if (gdrivePickerRow !== null)
                                        handleItemFieldChange(gdrivePickerRow, 'location', path);
                                    setGdrivePickerRow(null);
                                }}
                            />
                        )}
                    </Modal.Body>
                    <Modal.Footer>
                        <button
                            onClick={() => setGdrivePickerRow(null)}
                            className="px-4 py-2 bg-surface-alt text-fg rounded-lg hover:bg-surface-hover transition-colors min-h-11"
                        >
                            Close
                        </button>
                    </Modal.Footer>
                </Modal>
            </>
        );
    };

    if (field.alwaysExpanded) {
        return (
            <FieldWrapper invalid={highlightInvalid} variant="standard">
                <div className="flex items-center justify-between gap-3">
                    <FieldLabel label={field.label} required={field.required} />
                    <AddButton
                        onClick={handleAddExpanded}
                        disabled={disabled}
                        itemType={displayTemplate.itemName}
                        text={`Add ${displayTemplate.itemName}`}
                    />
                </div>

                <div className="flex flex-col gap-3 mt-1" id={inputId}>
                    {field.bulkPreset && (
                        <BulkPresetPicker
                            field={field}
                            value={value}
                            onChange={onChange}
                            disabled={disabled}
                        />
                    )}
                    {field.displayType === 'gdrive' ? (
                        renderGdriveTable()
                    ) : value.length > 0 ? (
                        value.map((item, index) =>
                            field.displayType === 'upgradinatorr'
                                ? renderUpgradinatorrCard(item, index)
                                : renderExpandedCard(item, index)
                        )
                    ) : (
                        <div className="p-8 text-center border border-dashed border-border rounded-lg bg-surface-alt">
                            <div className="text-sm text-fg-muted">
                                No {displayTemplate.itemName.toLowerCase()}s configured
                            </div>
                        </div>
                    )}
                </div>

                <FieldDescription id={`${inputId}-description`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />
            </FieldWrapper>
        );
    }

    return (
        <FieldWrapper invalid={highlightInvalid} variant="standard">
            <FieldLabel label={field.label} required={field.required} />

            <div className="flex flex-col gap-3 min-h-11" id={inputId}>
                {/* Optional bulk-add panel (e.g. GDrive presets) — appends to the
                    same array; manual single-add + editing stay on the list below */}
                {field.bulkPreset && (
                    <BulkPresetPicker
                        field={field}
                        value={value}
                        onChange={onChange}
                        disabled={disabled}
                    />
                )}

                {/* Existing items */}
                {value.length > 0 ? (
                    <div className="flex flex-col border border-border rounded-lg bg-surface overflow-hidden">
                        {value.map((item, index) => renderDisplayItem(item, index))}
                    </div>
                ) : (
                    <div className="p-8 text-center border border-dashed border-border rounded-lg bg-surface-alt">
                        <div className="text-sm text-fg-muted">
                            No {displayTemplate.itemName.toLowerCase()}s configured
                        </div>
                    </div>
                )}

                {/* Add form (only show when adding new item at bottom) */}
                {expandedIndex !== null && expandedIndex >= value.length && renderEditForm()}

                {/* Add button */}
                {expandedIndex === null && (
                    <div className="flex justify-start py-2">
                        <AddButton
                            onClick={handleAdd}
                            disabled={disabled}
                            itemType={displayTemplate.itemName}
                            text={`Add ${displayTemplate.itemName}`}
                        />
                    </div>
                )}
            </div>

            <FieldDescription id={`${inputId}-description`} description={field.description} />
            <FieldError id={`${inputId}-error`} message={errorMessage} />
        </FieldWrapper>
    );
};

/**
 * Display templates for different field types
 */
const DISPLAY_TEMPLATES = {
    gdrive: {
        itemName: 'Drive Location',
        display: item => ({
            primary: item.name || 'Unnamed Drive',
            secondary: item.location || 'No location specified',
            badge: item.id ? `ID: ${item.id.substring(0, 8)}...` : null,
        }),
    },
    replacerr: {
        itemName: 'Holiday Mapping',
        display: item => {
            let scheduleText = 'No schedule';
            if (item.schedule) {
                if (typeof item.schedule === 'string') {
                    scheduleText = item.schedule;
                } else if (item.schedule.start && item.schedule.end) {
                    scheduleText = `${item.schedule.start} to ${item.schedule.end}`;
                }
            }

            return {
                primary: item.name || 'Unknown Holiday',
                secondary: scheduleText,
                badge: item.colors ? `${item.colors.length} colors` : 'No colors',
            };
        },
    },
    upgradinatorr: {
        itemName: 'Upgrade Profile',
        display: item => {
            const schedule = item.schedule ? scheduleToHuman(item.schedule) : 'Main schedule only';
            // Array form lets the row renderer wrap segments as chips on mobile
            // instead of cramming them into one truncated pipe-separated string.
            return {
                primary: item.label || item.instance || 'Unknown Instance',
                secondary: [
                    item.instance || 'No instance',
                    `Tag: ${item.tag_name || 'checked'}`,
                    `Count: ${item.count || 0}`,
                    schedule,
                ],
                badge:
                    item.enabled === false ? 'Disabled' : item.unattended ? 'Auto reset' : 'Manual',
            };
        },
    },
    labelarr: {
        itemName: 'Tag Mapping',
        display: item => ({
            primary: item.app_instance || 'Unknown Instance',
            secondary: item.labels || 'No labels',
            badge: item.plex_instances?.length ? `${item.plex_instances.length} Plex` : 'No Plex',
        }),
    },
    nestarr: {
        itemName: 'Library Mapping',
        display: item => ({
            primary: item.arr_instance || 'Unknown Instance',
            secondary: item.plex_instances?.length
                ? item.plex_instances
                      .map(p => {
                          const name = p.instance || p.name || (typeof p === 'string' ? p : '');
                          const libs = (p.library_names || p.libraries)?.length || 0;
                          return libs > 0 ? `${name} (${libs} lib${libs !== 1 ? 's' : ''})` : name;
                      })
                      .join(', ')
                : 'No Plex instances',
            badge: null,
        }),
    },
    qualityGroup: {
        itemName: 'Quality Group',
        display: item => {
            const instances = Array.isArray(item.instances) ? item.instances : [];
            return {
                primary: instances.length ? instances.join(' + ') : 'Empty quality group',
                secondary:
                    instances.length >= 2
                        ? 'Excluded from duplicate detection'
                        : 'Add at least 2 instances',
                badge: instances.length ? `${instances.length} instances` : null,
            };
        },
    },
};

/**
 * Get display template for field type
 */
function getDisplayTemplate(fieldType) {
    // Direct mapping for displayType
    if (DISPLAY_TEMPLATES[fieldType]) {
        return DISPLAY_TEMPLATES[fieldType];
    }

    // Default fallback to gdrive template
    return DISPLAY_TEMPLATES.gdrive;
}

/**
 * Get field component from registry
 */
function getFieldComponent(fieldType) {
    return FieldRegistry.getField(fieldType);
}

ArrayObjectField.displayName = 'ArrayObjectField';
