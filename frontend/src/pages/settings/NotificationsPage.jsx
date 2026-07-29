import { useState, useCallback } from 'react';
import { ServiceIcon } from '../../components/ui';
import Toggle from '../../components/ui/Toggle';
import { Button } from '../../components/ui/button/Button';
import { Modal } from '../../components/modals/Modal';
import { useApiData } from '../../hooks/useApiData';
import { notificationsAPI, ALL_MODULES } from '../../utils/api/notifications';
import { FieldRegistry } from '../../components/fields/FieldRegistry';
import { NOTIFICATIONS_SCHEMA } from '../../utils/constants/notifications_schema';
import { useToast } from '../../contexts/ToastContext';
import { humanize } from '../../utils/tools';
import { moduleOrder } from '../../utils/constants/constants';
import { CONFIG_ONLY_MODULE_KEYS } from '../../utils/constants/settings_schema';
import { withExtensionConfigModuleKeys } from '../../extensions/index.js';

const REDACTED = '********';
const CHIP_LIMIT = 6;

// The modules a destination can report on — every runnable module in display
// order (extension modules spliced at their anchors), minus the non-notifiable
// "general"/"main" pseudo-sections and config-only modules (CL2K Maker) that
// never run to notify. Kept in sync with Settings → Modules, not hard-coded.
const MODULE_KEYS = withExtensionConfigModuleKeys(moduleOrder).filter(
    m => m !== 'general' && m !== 'main' && !CONFIG_ONLY_MODULE_KEYS.has(m)
);

// Method identity — tints/status are independent of the accent theme.
const METHOD = {
    discord: {
        label: 'Discord',
        tint: '#a99eff',
        tintBg: 'rgba(135,103,247,.14)',
        tintBorder: 'rgba(135,103,247,.32)',
        status: 'Direct',
        statusColor: '#6cbc66',
        statusRing: 'rgba(108,188,102,.16)',
        blurb: 'Post rich embeds straight into a channel with an incoming webhook URL. No account needed.',
        addLabel: 'Add webhook',
        noun: 'webhook',
    },
    notifiarr: {
        label: 'Notifiarr',
        tint: '#ff9d75',
        tintBg: 'rgba(255,157,117,.14)',
        tintBorder: 'rgba(255,157,117,.32)',
        status: 'Connected',
        statusColor: '#53e8f0',
        statusRing: 'rgba(83,232,240,.16)',
        blurb: 'Route alerts through your Notifiarr account — fan out to Discord, mobile push, Telegram & more.',
        addLabel: 'Add alert',
        noun: 'alert',
    },
};

const isAll = modules => Array.isArray(modules) && modules.includes(ALL_MODULES);

const selectedModules = modules => (isAll(modules) ? MODULE_KEYS : modules || []);

const targetLine = d =>
    d.method === 'discord'
        ? `Discord · incoming webhook${d.config?.bot_name ? ` · ${d.config.bot_name}` : ''}`
        : `Notifiarr · channel ${d.config?.channel_id ?? '—'}`;

/**
 * Notifications settings — per-destination outbound alerting.
 *
 * Each destination (a Discord webhook or Notifiarr alert) fans out to the
 * modules it should report on, with independent success/failure triggers and
 * an enable toggle. Wired to the destinations config/API.
 */
export const NotificationsPage = () => {
    const toast = useToast();

    const {
        data,
        isLoading,
        error,
        execute: refresh,
    } = useApiData({ apiFunction: notificationsAPI.fetchNotifications });

    // Local working mirror of the server's destinations list (optimistic UI).
    // Reset during render when a fresh server snapshot arrives — the React-
    // sanctioned "adjust state on prop change" pattern (no effect needed).
    const [dests, setDests] = useState([]);
    const [snapshot, setSnapshot] = useState(null);
    const serverList = data?.data?.destinations;
    if (Array.isArray(serverList) && serverList !== snapshot) {
        setSnapshot(serverList);
        setDests(serverList);
    }

    const [pickerOpen, setPickerOpen] = useState(null);
    const [modal, setModal] = useState(null); // { mode, method, id?, name, config, errors }
    const [deleteId, setDeleteId] = useState(null);
    const [testing, setTesting] = useState(() => new Set());
    const [busy, setBusy] = useState(false);

    // ── persistence ──────────────────────────────────────────────────────
    const persistDest = useCallback(
        async d => {
            try {
                await notificationsAPI.updateDestination(d.id, {
                    method: d.method,
                    name: d.name,
                    enabled: d.enabled,
                    events: d.events,
                    modules: d.modules,
                    config: d.config,
                });
            } catch (e) {
                toast.error(e.message || 'Failed to save destination');
                refresh({ useCache: false });
            }
        },
        [toast, refresh]
    );

    // Mutate a destination locally; persist immediately unless save=false (used
    // by the module picker, which batches its edits until "Done").
    const mutate = useCallback(
        (id, patch, save = true) => {
            const current = dests.find(d => d.id === id);
            if (!current) return;
            const updated = { ...current, ...patch };
            setDests(prev => prev.map(d => (d.id === id ? updated : d)));
            if (save) persistDest(updated);
        },
        [dests, persistDest]
    );

    const closePicker = useCallback(
        id => {
            const d = dests.find(x => x.id === id);
            if (d) persistDest(d);
            setPickerOpen(null);
        },
        [dests, persistDest]
    );

    // ── module picker actions ────────────────────────────────────────────
    const toggleModule = useCallback(
        (id, key) => {
            const d = dests.find(x => x.id === id);
            if (!d) return;
            const base = isAll(d.modules) ? [...MODULE_KEYS] : [...(d.modules || [])];
            const next = base.includes(key) ? base.filter(m => m !== key) : [...base, key];
            mutate(id, { modules: next }, false);
        },
        [dests, mutate]
    );

    const removeChip = useCallback(
        (id, key) => {
            const d = dests.find(x => x.id === id);
            if (!d) return;
            const base = isAll(d.modules) ? [...MODULE_KEYS] : [...(d.modules || [])];
            mutate(id, { modules: base.filter(m => m !== key) });
        },
        [dests, mutate]
    );

    // ── test ─────────────────────────────────────────────────────────────
    const handleTest = useCallback(
        async d => {
            setTesting(prev => new Set(prev).add(d.id));
            try {
                const res = await notificationsAPI.testDestination({
                    method: d.method,
                    config: d.config,
                    id: d.id,
                });
                toast.success(res?.message || 'Test notification sent');
            } catch (e) {
                toast.error(e.message || 'Test notification failed');
            } finally {
                setTesting(prev => {
                    const next = new Set(prev);
                    next.delete(d.id);
                    return next;
                });
            }
        },
        [toast]
    );

    // ── add / edit credential modal ──────────────────────────────────────
    const openAdd = method => setModal({ mode: 'add', method, name: '', config: {}, errors: {} });

    const openEdit = d =>
        setModal({
            mode: 'edit',
            method: d.method,
            id: d.id,
            name: d.name || '',
            config: { ...d.config },
            errors: {},
        });

    const setModalField = (key, value) =>
        setModal(m => ({
            ...m,
            config: { ...m.config, [key]: value },
            errors: { ...m.errors, [key]: undefined },
        }));

    const validateModal = () => {
        const schema = NOTIFICATIONS_SCHEMA.find(s => s.type === modal.method);
        const errors = {};
        schema?.fields.forEach(f => {
            const v = modal.config[f.key];
            if (v === REDACTED) return; // unchanged secret — leave as-is
            if (f.required && !v) errors[f.key] = `${f.label} is required`;
            else if (f.validate && v && !f.validate(v))
                errors[f.key] = `${f.label} format is invalid`;
        });
        setModal(m => ({ ...m, errors }));
        return Object.keys(errors).length === 0;
    };

    const saveModal = async () => {
        if (!validateModal()) {
            toast.error('Please fix the highlighted fields');
            return;
        }
        setBusy(true);
        try {
            if (modal.mode === 'add') {
                const res = await notificationsAPI.createDestination({
                    method: modal.method,
                    name: modal.name,
                    enabled: true,
                    events: { success: true, failure: false },
                    modules: [],
                    config: modal.config,
                });
                const newId = res?.data?.destination?.id;
                await refresh({ useCache: false });
                setModal(null);
                if (newId) setPickerOpen(newId); // pick modules straight away
            } else {
                const d = dests.find(x => x.id === modal.id);
                await notificationsAPI.updateDestination(modal.id, {
                    method: modal.method,
                    name: modal.name,
                    enabled: d?.enabled ?? true,
                    events: d?.events ?? { success: true, failure: false },
                    modules: d?.modules ?? [],
                    config: modal.config,
                });
                await refresh({ useCache: false });
                setModal(null);
            }
        } catch (e) {
            toast.error(e.message || 'Failed to save destination');
        } finally {
            setBusy(false);
        }
    };

    const confirmDelete = async () => {
        setBusy(true);
        try {
            await notificationsAPI.deleteDestination(deleteId);
            setDeleteId(null);
            await refresh({ useCache: false });
            toast.success('Destination deleted');
        } catch (e) {
            toast.error(e.message || 'Failed to delete destination');
        } finally {
            setBusy(false);
        }
    };

    // ── header ───────────────────────────────────────────────────────────
    const header = (
        <div className="min-w-0">
            <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                Notifications
            </h1>
            <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                Choose how CHUB reaches you, then point each destination at the modules it should
                report on.
            </p>
        </div>
    );

    if (isLoading) {
        return (
            <div className="flex flex-col gap-5">
                {header}
                <p className="text-fg-muted">Loading notifications…</p>
            </div>
        );
    }
    if (error) {
        return (
            <div className="flex flex-col gap-5">
                {header}
                <div className="text-center py-12">
                    <p className="text-error">Error loading notifications: {error.message}</p>
                    <Button variant="primary" onClick={refresh} className="mt-4">
                        Retry
                    </Button>
                </div>
            </div>
        );
    }

    const countFor = method => dests.filter(d => d.method === method).length;

    return (
        <div className="w-full max-w-[920px] mx-auto flex flex-col">
            {header}

            {/* NOTIFICATION METHODS */}
            <div className="font-mono text-[10px] tracking-[1.5px] text-fg-faint mt-[22px] mb-[11px]">
                NOTIFICATION METHODS
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-[14px] mb-[30px]">
                {['discord', 'notifiarr'].map(method => {
                    const m = METHOD[method];
                    const n = countFor(method);
                    return (
                        <div
                            key={method}
                            className="bg-surface border border-border rounded-[14px] p-[16px_18px] flex flex-col gap-3"
                        >
                            <div className="flex items-start gap-3">
                                <div
                                    className="shrink-0 w-10 h-10 rounded-[11px] flex items-center justify-center"
                                    style={{ background: m.tintBg }}
                                >
                                    <ServiceIcon service={method} size="small" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="font-display text-[15px] font-semibold text-fg">
                                            {m.label}
                                        </span>
                                        <span
                                            className="flex items-center gap-1.5 font-mono text-[10px]"
                                            style={{ color: m.statusColor }}
                                        >
                                            <span
                                                className="w-1.5 h-1.5 rounded-full"
                                                style={{
                                                    background: m.statusColor,
                                                    boxShadow: `0 0 0 3px ${m.statusRing}`,
                                                }}
                                            />
                                            {m.status}
                                        </span>
                                    </div>
                                    <div className="text-[12.5px] text-fg-data leading-[1.45] mt-1">
                                        {m.blurb}
                                    </div>
                                </div>
                            </div>
                            <div className="h-px bg-border-light" />
                            <div className="flex items-center justify-between">
                                <span className="font-mono text-[11.5px] text-fg-subtle">
                                    {n} {m.noun}
                                    {n === 1 ? '' : 's'}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => openAdd(method)}
                                    className="flex items-center gap-1.5 h-8 px-[13px] rounded-lg font-display text-[12.5px] font-semibold transition hover:brightness-110"
                                    style={{
                                        background: m.tintBg,
                                        border: `1px solid ${m.tintBorder}`,
                                        color: m.tint,
                                    }}
                                >
                                    <span className="material-symbols-outlined text-[15px]">
                                        add
                                    </span>
                                    {m.addLabel}
                                </button>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* DESTINATIONS, GROUPED BY METHOD */}
            {['discord', 'notifiarr'].map(method => {
                const m = METHOD[method];
                const group = dests.filter(d => d.method === method);
                return (
                    <div key={method} className="mb-[26px]">
                        <div className="flex items-center gap-2.5 mb-3">
                            <span style={{ color: m.tint }} className="flex">
                                <ServiceIcon service={method} size="small" />
                            </span>
                            <span className="font-display text-[14px] font-semibold tracking-[.2px] text-fg">
                                {m.label}
                            </span>
                            <span className="font-mono text-[10px] text-fg-faint px-[7px] py-0.5 rounded-full bg-surface-inset border border-border">
                                {group.length}
                            </span>
                            <span className="flex-1 h-px bg-border-light" />
                        </div>

                        <div className="flex flex-col gap-3">
                            {group.length === 0 ? (
                                <div className="border border-dashed border-border rounded-xl p-[18px] text-center text-[12.5px] text-fg-faint">
                                    No {m.label} destinations yet.
                                </div>
                            ) : (
                                group.map(d => (
                                    <DestinationCard
                                        key={d.id}
                                        d={d}
                                        meta={m}
                                        testing={testing.has(d.id)}
                                        pickerOpen={pickerOpen === d.id}
                                        onTest={() => handleTest(d)}
                                        onEdit={() => openEdit(d)}
                                        onDelete={() => setDeleteId(d.id)}
                                        onToggleEnabled={() =>
                                            mutate(d.id, { enabled: !d.enabled })
                                        }
                                        onToggleEvent={ev =>
                                            mutate(d.id, {
                                                events: {
                                                    ...d.events,
                                                    [ev]: !d.events?.[ev],
                                                },
                                            })
                                        }
                                        onRemoveChip={key => removeChip(d.id, key)}
                                        onOpenPicker={() => setPickerOpen(d.id)}
                                        onClosePicker={() => closePicker(d.id)}
                                        onToggleModule={key => toggleModule(d.id, key)}
                                        onSelectAll={() =>
                                            mutate(d.id, { modules: [ALL_MODULES] }, false)
                                        }
                                        onClearAll={() => mutate(d.id, { modules: [] }, false)}
                                    />
                                ))
                            )}
                        </div>
                    </div>
                );
            })}

            {modal && (
                <CredentialModal
                    modal={modal}
                    busy={busy}
                    onName={name => setModal(m => ({ ...m, name }))}
                    onField={setModalField}
                    onClose={() => setModal(null)}
                    onSave={saveModal}
                />
            )}

            {deleteId && (
                <Modal isOpen onClose={() => setDeleteId(null)} size="small">
                    <Modal.Header>Delete destination</Modal.Header>
                    <Modal.Body>
                        <p className="text-fg">
                            Remove this destination? Modules pointed at it will no longer report
                            here.
                        </p>
                    </Modal.Body>
                    <Modal.Footer>
                        <Button
                            variant="secondary"
                            onClick={() => setDeleteId(null)}
                            disabled={busy}
                        >
                            Cancel
                        </Button>
                        <Button variant="danger" onClick={confirmDelete} disabled={busy}>
                            {busy ? 'Deleting…' : 'Delete'}
                        </Button>
                    </Modal.Footer>
                </Modal>
            )}
        </div>
    );
};

// ── Destination card ─────────────────────────────────────────────────────
const DestinationCard = ({
    d,
    meta,
    testing,
    pickerOpen,
    onTest,
    onEdit,
    onDelete,
    onToggleEnabled,
    onToggleEvent,
    onRemoveChip,
    onOpenPicker,
    onClosePicker,
    onToggleModule,
    onSelectAll,
    onClearAll,
}) => {
    const all = isAll(d.modules);
    const selected = selectedModules(d.modules);
    const chips = all ? [] : selected.slice(0, CHIP_LIMIT);
    const more = all ? 0 : Math.max(0, selected.length - CHIP_LIMIT);

    return (
        <div
            className="relative rounded-[13px] bg-surface border border-border transition-colors hover:border-[#3b3d72]"
            style={{ opacity: d.enabled ? 1 : 0.62 }}
        >
            {/* header band */}
            <div className="flex items-center gap-[14px] p-[15px_17px]">
                <div
                    className="shrink-0 w-10 h-10 rounded-[10px] flex items-center justify-center"
                    style={{ background: meta.tintBg }}
                >
                    <ServiceIcon service={d.method} size="small" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5">
                        <span className="font-display text-[15px] font-semibold text-fg truncate">
                            {d.name || meta.label}
                        </span>
                        <span
                            className="font-mono text-[9px] uppercase tracking-[.5px] px-1.5 py-0.5 rounded-[5px]"
                            style={{ background: meta.tintBg, color: meta.tint }}
                        >
                            {meta.label}
                        </span>
                    </div>
                    <div className="font-mono text-[11.5px] text-fg-subtle mt-1 truncate">
                        {targetLine(d)}
                    </div>
                </div>
                <div className="shrink-0 flex items-center gap-1">
                    <button
                        type="button"
                        onClick={onTest}
                        disabled={testing}
                        className="h-[30px] px-[11px] rounded-[7px] bg-transparent border border-border text-fg-data text-[12px] font-semibold transition-colors hover:bg-[#221c45] disabled:opacity-60"
                    >
                        {testing ? 'Testing…' : 'Test'}
                    </button>
                    <IconBtn icon="edit" label="Edit destination" onClick={onEdit} />
                    <IconBtn icon="delete" label="Delete destination" onClick={onDelete} />
                    <Toggle
                        checked={d.enabled}
                        onChange={onToggleEnabled}
                        label="Enable destination"
                        className="ml-1.5"
                    />
                </div>
            </div>

            <div className="h-px bg-border-light mx-[17px]" />

            {/* triggers + modules */}
            <div className="flex flex-col gap-[13px] p-[14px_17px_16px]">
                <div className="flex items-center gap-[14px]">
                    <span className="font-mono text-[9.5px] tracking-[1px] text-fg-faint w-16 shrink-0">
                        TRIGGER
                    </span>
                    <div className="flex gap-2">
                        <TriggerPill
                            active={!!d.events?.success}
                            label="On success"
                            tone="success"
                            onClick={() => onToggleEvent('success')}
                        />
                        <TriggerPill
                            active={!!d.events?.failure}
                            label="On failure"
                            tone="failure"
                            onClick={() => onToggleEvent('failure')}
                        />
                    </div>
                </div>

                <div className="flex items-start gap-[14px]">
                    <span className="font-mono text-[9.5px] tracking-[1px] text-fg-faint w-16 shrink-0 pt-1.5">
                        MODULES
                    </span>
                    <div className="flex-1 min-w-0 flex flex-wrap items-center gap-[7px]">
                        {all && (
                            <span
                                className="flex items-center gap-1.5 px-[11px] py-1 rounded-[7px] text-[12px] font-semibold"
                                style={{
                                    background: 'rgba(135,103,247,.13)',
                                    border: '1px solid rgba(135,103,247,.3)',
                                    color: '#a99eff',
                                }}
                            >
                                <span className="material-symbols-outlined text-[14px]">check</span>
                                All modules
                            </span>
                        )}
                        {!all && selected.length === 0 && (
                            <span className="text-[12.5px] text-fg-faint italic py-1">
                                No modules yet — pick which runs report here.
                            </span>
                        )}
                        {chips.map(key => (
                            <span
                                key={key}
                                className="group flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-[7px] bg-surface-inset border border-border text-fg-muted text-[12px] font-medium"
                            >
                                {humanize(key)}
                                <button
                                    type="button"
                                    aria-label={`Remove ${humanize(key)}`}
                                    onClick={() => onRemoveChip(key)}
                                    className="flex opacity-45 group-hover:opacity-100 transition-opacity"
                                >
                                    <span className="material-symbols-outlined text-[14px]">
                                        close
                                    </span>
                                </button>
                            </span>
                        ))}
                        {more > 0 && (
                            <span className="font-mono text-[11px] text-fg-subtle px-1 py-1">
                                +{more} more
                            </span>
                        )}
                        <button
                            type="button"
                            onClick={onOpenPicker}
                            className="flex items-center gap-1.5 px-2.5 py-1 rounded-[7px] bg-transparent text-fg-data text-[12px] font-semibold transition-colors hover:bg-[#191636]"
                            style={{ border: '1px dashed #3b3d72' }}
                        >
                            <span className="material-symbols-outlined text-[14px]">add</span>
                            Select modules
                        </button>
                    </div>
                </div>
            </div>

            {pickerOpen && (
                <ModulePicker
                    selected={selected}
                    all={all}
                    onToggle={onToggleModule}
                    onSelectAll={onSelectAll}
                    onClearAll={onClearAll}
                    onDone={onClosePicker}
                />
            )}
        </div>
    );
};

const IconBtn = ({ icon, label, onClick }) => (
    <button
        type="button"
        aria-label={label}
        onClick={onClick}
        className="w-[30px] h-[30px] rounded-[7px] bg-transparent text-fg-subtle flex items-center justify-center transition-colors hover:bg-[#221c45] hover:text-fg-muted"
    >
        <span className="material-symbols-outlined text-[16px]">{icon}</span>
    </button>
);

const TriggerPill = ({ active, label, tone, onClick }) => {
    const colors =
        tone === 'success'
            ? { c: '#6cbc66', bg: 'rgba(108,188,102,.12)', b: 'rgba(108,188,102,.4)' }
            : { c: '#fd355c', bg: 'rgba(253,53,92,.12)', b: 'rgba(253,53,92,.4)' };
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex items-center gap-1.5 px-[11px] py-[5px] rounded-full text-[12px] font-semibold transition-colors"
            style={{
                color: active ? colors.c : '#6582ca',
                background: active ? colors.bg : 'transparent',
                border: `1px solid ${active ? colors.b : '#2a3052'}`,
            }}
        >
            {active && <span className="material-symbols-outlined text-[14px]">check</span>}
            {label}
        </button>
    );
};

// ── Module multiselect popover ───────────────────────────────────────────
const ModulePicker = ({ selected, all, onToggle, onSelectAll, onClearAll, onDone }) => {
    const isChecked = key => all || selected.includes(key);
    return (
        <div
            className="absolute z-30 right-[17px] bottom-[14px] w-[340px] max-w-[calc(100vw-34px)] rounded-[12px] overflow-hidden"
            style={{
                background: '#15112e',
                border: '1px solid #3b3d72',
                boxShadow: '0 18px 48px -12px rgba(0,0,0,.7)',
            }}
        >
            <div className="flex items-center justify-between p-[12px_14px] border-b border-border-light">
                <span className="font-display text-[13px] font-semibold text-fg">
                    Report to this destination
                </span>
                <span className="font-mono text-[10.5px] text-fg-subtle">
                    {all ? MODULE_KEYS.length : selected.length} of {MODULE_KEYS.length}
                </span>
            </div>
            <div className="flex gap-[7px] p-[10px_14px] border-b border-border-light">
                <button
                    type="button"
                    onClick={onSelectAll}
                    className="flex-1 h-7 rounded-[7px] bg-surface-inset border border-border text-fg-muted text-[11.5px] font-semibold"
                >
                    Select all
                </button>
                <button
                    type="button"
                    onClick={onClearAll}
                    className="flex-1 h-7 rounded-[7px] bg-surface-inset border border-border text-fg-data text-[11.5px] font-semibold"
                >
                    Clear
                </button>
            </div>
            <div className="max-h-[240px] overflow-y-auto p-[5px]">
                {MODULE_KEYS.map(key => {
                    const checked = isChecked(key);
                    return (
                        <button
                            type="button"
                            key={key}
                            onClick={() => onToggle(key)}
                            className="w-full flex items-center gap-2.5 p-[8px_9px] rounded-lg transition-colors hover:bg-row-hover text-left"
                        >
                            <span
                                className="shrink-0 w-[17px] h-[17px] rounded-[5px] flex items-center justify-center"
                                style={{
                                    border: `1.5px solid ${checked ? 'var(--primary)' : '#3b3d72'}`,
                                    background: checked ? 'var(--primary)' : 'transparent',
                                }}
                            >
                                {checked && (
                                    <span className="material-symbols-outlined text-[13px] text-on-color">
                                        check
                                    </span>
                                )}
                            </span>
                            <span
                                className={`text-[13px] ${checked ? 'text-fg font-semibold' : 'text-fg-muted font-medium'}`}
                            >
                                {humanize(key)}
                            </span>
                        </button>
                    );
                })}
            </div>
            <div className="p-[10px_14px] border-t border-border-light flex justify-end">
                <button
                    type="button"
                    onClick={onDone}
                    className="h-[30px] px-4 rounded-lg bg-primary text-on-color font-display text-[12.5px] font-semibold"
                >
                    Done
                </button>
            </div>
        </div>
    );
};

// ── Add / edit credential modal ──────────────────────────────────────────
const CredentialModal = ({ modal, busy, onName, onField, onClose, onSave }) => {
    const schema = NOTIFICATIONS_SCHEMA.find(s => s.type === modal.method);
    const title = `${modal.mode === 'add' ? 'Add' : 'Edit'} ${METHOD[modal.method].label} destination`;
    return (
        <Modal isOpen onClose={onClose} size="medium">
            <Modal.Header>{title}</Modal.Header>
            <Modal.Body>
                <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-1.5">
                        <label className="text-[13px] font-medium text-fg-muted">
                            Display name
                        </label>
                        <input
                            type="text"
                            value={modal.name}
                            onChange={e => onName(e.target.value)}
                            placeholder={modal.method === 'discord' ? 'My CHUB' : 'Homelab'}
                            className="h-10 px-3 rounded-lg bg-surface-inset border border-border text-fg text-[14px] outline-none focus:border-[#3b3d72]"
                        />
                    </div>
                    {schema?.fields.map(field => {
                        const FieldComponent = FieldRegistry.getField(field.type);
                        // destinations is a list keyed by a stable id; reveal
                        // resolves the saved secret by that id, not list order.
                        const secretField =
                            field.type === 'password' && modal.mode === 'edit' && modal.id
                                ? {
                                      ...field,
                                      secretPath: `notifications.destinations.${modal.id}.config.${field.key}`,
                                  }
                                : field;
                        return (
                            <FieldComponent
                                key={field.key}
                                field={secretField}
                                value={modal.config[field.key] || ''}
                                onChange={value => onField(field.key, value)}
                                errorMessage={modal.errors[field.key]}
                                highlightInvalid={!!modal.errors[field.key]}
                            />
                        );
                    })}
                </div>
            </Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={onClose} disabled={busy}>
                    Cancel
                </Button>
                <Button variant="primary" onClick={onSave} disabled={busy}>
                    {busy ? 'Saving…' : modal.mode === 'add' ? 'Add destination' : 'Save'}
                </Button>
            </Modal.Footer>
        </Modal>
    );
};
