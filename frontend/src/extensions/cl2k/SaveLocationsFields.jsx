// CL2K maker — Save Locations settings UI (design_handoff_cl2k_save_locations,
// option 2a: routed cards + coverage strip).
//
// Three custom field types registered by manifest.jsx via FieldRegistry.register
// (a public extension slot — no shared-file edits): the Local Folders and Google
// Drives cards edit their own config key (local_folders / gdrive_uploads); the
// Coverage card is read-only. ModuleSettingsPage's field memo only re-renders on
// a field's OWN value, so the two list fields publish into a tiny module-scope
// store and the coverage field subscribes to it (its rootConfig prop goes stale
// as siblings edit).
import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
    useSyncExternalStore,
} from 'react';
import { Modal } from '../../components/ui';
import { FieldRegistry } from '../../components/fields/FieldRegistry.jsx';
import { apiCore } from '../../utils/api/core';
import { useToast } from '../../contexts/ToastContext.jsx';

export const CL2K_ART_TYPES = [
    { value: 'poster', label: 'Poster' },
    { value: 'logo', label: 'Logo' },
    { value: 'background', label: 'Background' },
    { value: 'squareart', label: 'Square Art' },
];

const COVERAGE_LABELS = {
    poster: 'Poster',
    logo: 'Logo',
    background: 'Background',
    squareart: 'Square',
};

// Resolved once at module scope (manifests are eagerly imported at app init,
// after the registry's own module graph) — resolving inside render trips
// react-hooks/static-components.
const DirPickerField = FieldRegistry.getField('dir_picker');

// ─── Live-coverage store ─────────────────────────────────────────────────────

const coverageStore = {
    state: { local_folders: null, gdrive_uploads: null },
    listeners: new Set(),
};

const publishSaveLocations = (key, value) => {
    if (coverageStore.state[key] === value) return;
    coverageStore.state = { ...coverageStore.state, [key]: value };
    coverageStore.listeners.forEach(fn => fn());
};

const subscribeCoverage = fn => {
    coverageStore.listeners.add(fn);
    return () => coverageStore.listeners.delete(fn);
};

const coverageSnapshot = () => coverageStore.state;

// ─── Shared bits ─────────────────────────────────────────────────────────────

const Icon = ({ name, className = '', style }) => (
    <span
        className={`material-symbols-outlined leading-none select-none ${className}`}
        style={style}
        aria-hidden="true"
    >
        {name}
    </span>
);

const AddButton = ({ label, onClick, disabled }) => (
    <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 h-8 px-3 shrink-0 rounded-lg border border-border bg-surface-elevated text-fg-muted text-[12.5px] font-medium hover:text-fg hover:border-primary/50 disabled:opacity-50 transition-colors"
    >
        <Icon name="add" className="text-[16px]" />
        {label}
    </button>
);

// Card header: description left (the title itself is the section card's h2),
// "+ Add …" action right. Hidden while the empty state shows — it repeats the
// same button.
const CardIntro = ({ description, action }) => (
    <div className="flex items-start justify-between gap-3 -mt-3 mb-3.5">
        <p className="text-[12.5px] leading-[1.45] text-fg-subtle max-w-[480px] m-0">
            {description}
        </p>
        {action}
    </div>
);

// The routing UI: one toggling pill per artwork type.
const TypeChips = ({ microLabel, types, onToggle, disabled }) => (
    <div className="flex items-center gap-[7px] flex-wrap">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-fg-faint mr-0.5">
            {microLabel}
        </span>
        {CL2K_ART_TYPES.map(t => {
            const selected = (types || []).includes(t.value);
            return (
                <button
                    key={t.value}
                    type="button"
                    role="checkbox"
                    aria-checked={selected}
                    disabled={disabled}
                    onClick={() => onToggle(t.value)}
                    className={`inline-flex items-center gap-[5px] h-7 px-[11px] rounded-full text-[12.5px] font-medium border transition-colors duration-150 disabled:opacity-50 ${
                        selected
                            ? 'bg-primary/15 border-primary/65'
                            : 'bg-transparent border-border text-fg-subtle hover:border-primary/40'
                    }`}
                    style={selected ? { color: 'var(--primary-hover)' } : undefined}
                >
                    {selected && <Icon name="check" className="text-[14px]" />}
                    {t.label}
                </button>
            );
        })}
    </div>
);

const EmptyState = ({ icon, heading, body, actionLabel, onAdd, disabled }) => (
    <div className="flex flex-col items-center gap-2 text-center border border-dashed border-border rounded-[10px] p-[26px]">
        <Icon name={icon} className="text-[24px] text-fg-dim" />
        <p className="text-[13.5px] font-medium text-fg-muted m-0">{heading}</p>
        <p className="text-[12.5px] leading-[1.45] text-fg-subtle max-w-[400px] m-0">{body}</p>
        <div className="mt-1">
            <AddButton label={actionLabel} onClick={onAdd} disabled={disabled} />
        </div>
    </div>
);

const NameRow = ({
    icon,
    iconClass,
    entry,
    onRename,
    onDelete,
    disabled,
    nameRef,
    deleteLabel,
}) => (
    <div className="flex items-center gap-[9px]">
        <Icon name={icon} className={`text-[18px] ${iconClass}`} />
        <input
            ref={nameRef}
            type="text"
            value={entry.name || ''}
            placeholder="Name"
            disabled={disabled}
            onChange={e => onRename(e.target.value)}
            className="flex-1 min-w-0 bg-transparent border-none p-0 text-sm font-semibold text-fg placeholder:text-fg-dim focus:outline-none"
            aria-label="Location name"
        />
        <button
            type="button"
            onClick={onDelete}
            disabled={disabled}
            aria-label={deleteLabel}
            className="text-fg-dim hover:text-error disabled:opacity-50 transition-colors"
        >
            <Icon name="delete" className="text-[18px]" />
        </button>
    </div>
);

// Entry-list plumbing shared by both cards: append-in-edit-state (focus the new
// row's name, scroll it into view), per-row patch, immediate delete (existing
// CHUB pages don't confirm).
const useEntryList = (value, onChange, blankEntry) => {
    const entries = useMemo(() => (Array.isArray(value) ? value : []), [value]);
    const [focusIndex, setFocusIndex] = useState(null);

    const add = useCallback(() => {
        setFocusIndex(entries.length);
        onChange([...entries, { ...blankEntry }]);
    }, [entries, onChange, blankEntry]);

    const patch = useCallback(
        (index, changes) => {
            onChange(entries.map((e, i) => (i === index ? { ...e, ...changes } : e)));
        },
        [entries, onChange]
    );

    const remove = useCallback(
        index => {
            onChange(entries.filter((_, i) => i !== index));
        },
        [entries, onChange]
    );

    const toggleType = useCallback(
        (index, type) => {
            const current = entries[index]?.types || [];
            patch(index, {
                types: current.includes(type)
                    ? current.filter(t => t !== type)
                    : [...current, type],
            });
        },
        [entries, patch]
    );

    return { entries, add, patch, remove, toggleType, focusIndex, setFocusIndex };
};

const useAutoFocus = (isTarget, clear) => {
    const ref = useRef(null);
    useEffect(() => {
        if (isTarget && ref.current) {
            ref.current.focus();
            ref.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            clear();
        }
    }, [isTarget, clear]);
    return ref;
};

// ─── Local Folders card ──────────────────────────────────────────────────────

const FolderEntry = ({
    entry,
    disabled,
    onPatch,
    onDelete,
    onToggleType,
    onBrowse,
    autoFocus,
    clearFocus,
}) => {
    const nameRef = useAutoFocus(autoFocus, clearFocus);
    return (
        <div className="flex flex-col gap-[11px] bg-surface-inset border border-border-light rounded-[10px] px-4 py-3.5">
            <NameRow
                icon="folder"
                iconClass="text-source-local"
                entry={entry}
                onRename={name => onPatch({ name })}
                onDelete={onDelete}
                disabled={disabled}
                nameRef={nameRef}
                deleteLabel="Delete folder"
            />
            <div className="flex gap-2">
                <input
                    type="text"
                    value={entry.path || ''}
                    placeholder="/path/to/folder"
                    disabled={disabled}
                    onChange={e => onPatch({ path: e.target.value })}
                    className="flex-1 min-w-0 h-[38px] px-3 bg-bg border border-border rounded-lg font-mono text-[12.5px] text-fg-muted placeholder:text-fg-dim focus:ring-primary focus:outline-none transition-colors"
                    aria-label="Folder path"
                />
                <button
                    type="button"
                    onClick={onBrowse}
                    disabled={disabled}
                    aria-label="Browse for folder"
                    className="w-[38px] h-[38px] shrink-0 inline-flex items-center justify-center bg-surface border border-border rounded-lg text-fg-muted hover:text-fg hover:border-primary/50 disabled:opacity-50 transition-colors"
                >
                    <Icon name="folder_open" className="text-[17px]" />
                </button>
            </div>
            <TypeChips
                microLabel="Saves"
                types={entry.types}
                onToggle={onToggleType}
                disabled={disabled}
            />
        </div>
    );
};

export const Cl2kLocalFoldersField = ({ value, onChange, disabled = false }) => {
    const { entries, add, patch, remove, toggleType, focusIndex, setFocusIndex } = useEntryList(
        value,
        onChange,
        { name: '', path: '', types: [] }
    );
    const [browseIndex, setBrowseIndex] = useState(null);

    useEffect(() => {
        publishSaveLocations('local_folders', Array.isArray(value) ? value : []);
    }, [value]);

    const clearFocus = useCallback(() => setFocusIndex(null), [setFocusIndex]);

    return (
        <div>
            <CardIntro
                description="Save generated art into folders on disk, routed by artwork type. Optional — with no folders, art is only available from the maker page."
                action={
                    entries.length > 0 && (
                        <AddButton label="Add folder" onClick={add} disabled={disabled} />
                    )
                }
            />
            {entries.length === 0 ? (
                <EmptyState
                    icon="folder_off"
                    heading="No local folders"
                    body="Generated art stays available from the maker page — add a folder to save it automatically."
                    actionLabel="Add folder"
                    onAdd={add}
                    disabled={disabled}
                />
            ) : (
                <div className="flex flex-col gap-2.5">
                    {entries.map((entry, i) => (
                        <FolderEntry
                            key={i}
                            entry={entry}
                            disabled={disabled}
                            onPatch={changes => patch(i, changes)}
                            onDelete={() => remove(i)}
                            onToggleType={type => toggleType(i, type)}
                            onBrowse={() => setBrowseIndex(i)}
                            autoFocus={focusIndex === i}
                            clearFocus={clearFocus}
                        />
                    ))}
                </div>
            )}

            <Modal isOpen={browseIndex !== null} onClose={() => setBrowseIndex(null)} size="large">
                <Modal.Header>Select Directory</Modal.Header>
                <Modal.Body>
                    {DirPickerField && browseIndex !== null && (
                        <DirPickerField
                            field={{
                                key: 'cl2k_folder_browser',
                                label: 'Directory Browser',
                                type: 'dir_picker',
                                description: 'Browse and select a directory',
                            }}
                            value={entries[browseIndex]?.path || ''}
                            onChange={newPath => {
                                patch(browseIndex, { path: newPath });
                                setBrowseIndex(null);
                            }}
                        />
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <button
                        onClick={() => setBrowseIndex(null)}
                        className="px-4 py-2 bg-surface-alt text-fg rounded-lg hover:bg-surface-hover transition-colors min-h-11"
                    >
                        Close
                    </button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

// ─── Google Drives card ──────────────────────────────────────────────────────

const TestUploadButton = ({ folderId, disabled }) => {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const canRun = !disabled && !busy && !!(folderId || '').trim();

    const run = useCallback(async () => {
        setBusy(true);
        try {
            const res = await apiCore.post('/cl2k-maker/test-drive', {
                gdrive_folder_id: folderId,
            });
            toast.success(res?.message || 'Upload works');
        } catch (e) {
            toast.error(e?.message || 'Upload test failed');
        } finally {
            setBusy(false);
        }
    }, [folderId, toast]);

    return (
        <button
            type="button"
            onClick={run}
            disabled={!canRun}
            title={(folderId || '').trim() ? undefined : 'Enter a Folder ID to test'}
            className="inline-flex items-center gap-1.5 h-[38px] px-3 shrink-0 bg-surface border border-border rounded-lg text-fg-muted text-[12.5px] font-medium hover:text-fg hover:border-primary/50 disabled:opacity-50 transition-colors"
        >
            <Icon name="cloud_upload" className="text-[16px] text-accent" />
            {busy ? 'Testing…' : 'Test upload'}
        </button>
    );
};

// Splits ONE parent Drive into the community artwork layout. Opt-in per row —
// a Drive that should stay flat simply never uses it, and nothing on Drive is
// moved or deleted either way.
const SplitSubfoldersButton = ({ folderId, disabled, onSplit }) => {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const canRun = !disabled && !busy && !!(folderId || '').trim();

    const run = useCallback(async () => {
        setBusy(true);
        try {
            const res = await apiCore.post('/cl2k-maker/gdrive/type-subfolders', {
                gdrive_folder_id: folderId,
            });
            const subfolders = res?.data?.subfolders || [];
            // Refuse to rewrite the row on a partial answer: a missing type or a
            // blank folder_id would save a destination that silently uploads
            // nothing (_drive_targets skips a blank id).
            const usable =
                CL2K_ART_TYPES.filter(t => t.value !== 'poster').every(t =>
                    subfolders.some(s => s.image_type === t.value && (s.folder_id || '').trim())
                ) && subfolders.every(s => (s.folder_id || '').trim());
            if (!usable) throw new Error('Drive returned an incomplete set of subfolders');
            onSplit(subfolders);
            toast.success(res?.message || 'Split into type subfolders');
        } catch (e) {
            toast.error(e?.message || 'Could not create the type subfolders');
        } finally {
            setBusy(false);
        }
    }, [folderId, toast, onSplit]);

    return (
        <button
            type="button"
            onClick={run}
            disabled={!canRun}
            title={
                (folderId || '').trim()
                    ? 'Create logos/backgrounds/squareart in this Drive folder and route each type to its own'
                    : 'Enter a Folder ID first'
            }
            className="inline-flex items-center gap-1.5 h-[38px] px-3 shrink-0 bg-surface border border-border rounded-lg text-fg-muted text-[12.5px] font-medium hover:text-fg hover:border-primary/50 disabled:opacity-50 transition-colors"
        >
            <Icon name="create_new_folder" className="text-[16px] text-accent" />
            {busy ? 'Splitting…' : 'Split by type'}
        </button>
    );
};

const DriveEntry = ({
    entry,
    disabled,
    onPatch,
    onDelete,
    onToggleType,
    onSplit,
    autoFocus,
    clearFocus,
}) => {
    const nameRef = useAutoFocus(autoFocus, clearFocus);
    return (
        <div className="flex flex-col gap-[11px] bg-surface-inset border border-border-light rounded-[10px] px-4 py-3.5">
            <NameRow
                icon="cloud"
                iconClass="text-source-gdrive"
                entry={entry}
                onRename={name => onPatch({ name })}
                onDelete={onDelete}
                disabled={disabled}
                nameRef={nameRef}
                deleteLabel="Delete Drive upload"
            />
            <div className="flex gap-2">
                <input
                    type="text"
                    value={entry.folder_id || ''}
                    placeholder="Drive folder ID"
                    disabled={disabled}
                    onChange={e => onPatch({ folder_id: e.target.value })}
                    className="flex-1 min-w-0 h-[38px] px-3 bg-bg border border-border rounded-lg font-mono text-[12.5px] text-fg-muted placeholder:text-fg-dim truncate focus:ring-primary focus:outline-none transition-colors"
                    aria-label="Drive folder ID"
                />
                <TestUploadButton folderId={entry.folder_id} disabled={disabled} />
                <SplitSubfoldersButton
                    folderId={entry.folder_id}
                    disabled={disabled}
                    onSplit={onSplit}
                />
            </div>
            <TypeChips
                microLabel="Uploads"
                types={entry.types}
                onToggle={onToggleType}
                disabled={disabled}
            />
        </div>
    );
};

export const Cl2kGdriveUploadsField = ({ value, onChange, disabled = false }) => {
    const { entries, add, patch, remove, toggleType, focusIndex, setFocusIndex } = useEntryList(
        value,
        onChange,
        { name: '', folder_id: '', types: [] }
    );

    useEffect(() => {
        publishSaveLocations('gdrive_uploads', Array.isArray(value) ? value : []);
    }, [value]);

    const clearFocus = useCallback(() => setFocusIndex(null), [setFocusIndex]);

    // Replace the split row with one routed row per type. The parent row's own
    // claimed types are dropped — they now live on the children — and any type
    // it didn't claim is left unclaimed rather than silently switched on.
    const splitRow = useCallback(
        (index, subfolders) => {
            const parent = entries[index] || {};
            const claimed = parent.types || [];
            const children = subfolders
                // Only types the parent actually claimed. An unclaimed row splits
                // into nothing and is left untouched by the empty-children return.
                .filter(s => claimed.includes(s.image_type))
                .map(s => ({
                    name: `${parent.name || 'Drive'} ${s.name}`.trim(),
                    folder_id: s.folder_id,
                    types: [s.image_type],
                }));
            if (children.length === 0) return;
            onChange(entries.flatMap((e, i) => (i === index ? children : [e])));
        },
        [entries, onChange]
    );

    return (
        <div>
            <CardIntro
                description="Also upload generated art to Drive folders you own, routed by artwork type."
                action={
                    entries.length > 0 && (
                        <AddButton label="Add Drive" onClick={add} disabled={disabled} />
                    )
                }
            />
            {entries.length === 0 ? (
                <EmptyState
                    icon="cloud_off"
                    heading="No Drive uploads"
                    body="Add a Drive to upload finished art to folders you own. Uploads use your Sync GDrive OAuth token — set one under Sync GDrive."
                    actionLabel="Add Drive"
                    onAdd={add}
                    disabled={disabled}
                />
            ) : (
                <div className="flex flex-col gap-2.5">
                    {entries.map((entry, i) => (
                        <DriveEntry
                            key={i}
                            entry={entry}
                            disabled={disabled}
                            onPatch={changes => patch(i, changes)}
                            onDelete={() => remove(i)}
                            onToggleType={type => toggleType(i, type)}
                            onSplit={subfolders => splitRow(i, subfolders)}
                            autoFocus={focusIndex === i}
                            clearFocus={clearFocus}
                        />
                    ))}
                </div>
            )}
            <div className="flex items-start gap-2 mt-3.5 pt-[13px] border-t border-border-light">
                <Icon name="info" className="text-[16px] text-accent mt-px" />
                <p className="text-[12.5px] leading-[1.45] text-fg-subtle m-0">
                    Uploads use your Sync GDrive OAuth token — set one under Sync GDrive. A service
                    account can&apos;t own files in a personal Drive, so it has no usable upload
                    path.
                </p>
            </div>
        </div>
    );
};

// ─── Coverage strip ──────────────────────────────────────────────────────────

export const Cl2kCoverageField = ({ rootConfig }) => {
    const lists = useSyncExternalStore(subscribeCoverage, coverageSnapshot);
    // Before the list fields' first publish (initial mount), fall back to the
    // loaded config.
    const localFolders = lists.local_folders ?? rootConfig?.cl2k_maker?.local_folders ?? [];
    const gdriveUploads = lists.gdrive_uploads ?? rootConfig?.cl2k_maker?.gdrive_uploads ?? [];

    return (
        <div>
            <p className="text-[12px] leading-[1.45] text-fg-subtle -mt-3 mb-2.5 m-0">
                Types nobody claims aren&apos;t auto-saved — still downloadable from the maker page.
            </p>
            <div className="flex flex-col sm:flex-row gap-2.5">
                {CL2K_ART_TYPES.map(t => {
                    const count =
                        localFolders.filter(f => (f?.types || []).includes(t.value)).length +
                        gdriveUploads.filter(d => (d?.types || []).includes(t.value)).length;
                    const covered = count > 0;
                    return (
                        <div
                            key={t.value}
                            className={`flex-1 rounded-lg px-3 py-[9px] ${
                                covered
                                    ? 'bg-surface-inset'
                                    : 'bg-warning-bg border border-warning/25'
                            }`}
                        >
                            <div
                                className={`text-[10.5px] font-semibold uppercase tracking-[0.06em] ${
                                    covered ? 'text-fg-faint' : 'text-warning'
                                }`}
                            >
                                {COVERAGE_LABELS[t.value]}
                            </div>
                            {covered ? (
                                <div className="text-[12.5px] text-fg mt-0.5">
                                    <span className="font-mono font-semibold">{count}</span>{' '}
                                    {count === 1 ? 'location' : 'locations'}
                                </div>
                            ) : (
                                <div className="flex items-center gap-[5px] text-[12.5px] text-warning mt-0.5">
                                    <Icon name="download" className="text-[14px]" />
                                    Download only
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
            {/* Page footer note (spec: below the location sections, all options). A
                field can't render outside its section card, so it closes this card. */}
            <div className="flex items-start gap-2 mt-3.5 px-1">
                <Icon name="info" className="text-[16px] text-accent mt-px" />
                <p className="text-[12.5px] leading-[1.45] text-fg-subtle m-0">
                    Anything not routed above isn&apos;t auto-saved — every generation stays
                    downloadable from the maker page.
                </p>
            </div>
        </div>
    );
};
