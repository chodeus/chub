import React, { useMemo, useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { webhooksAPI } from '../../utils/api/webhooks.js';
import { copyText } from '../../utils/clipboard.js';
import { IconButton } from '../../components/ui';

const buildPosterAddUrl = (path, secret) => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const base = `${origin}${path || '/api/webhooks/poster/add'}`;
    if (!secret) return base;
    return `${base}?secret=${encodeURIComponent(secret)}`;
};

/** Relative "Xh ago" for the LAST column. */
const timeAgo = iso => {
    if (!iso) return '—';
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return '—';
    const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (secs < 60) return 'just now';
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
};

/** The collapsible secret + wiring instructions (preserved from the original
 *  page so nothing is lost when reshaping to the mock's telemetry table). */
const SetupDetails = ({ wiring }) => {
    const toast = useToast();
    const [open, setOpen] = useState(false);
    const [revealSecret, setRevealSecret] = useState(false);

    const secretConfigured = !!wiring.secret_configured;
    const secret = wiring.secret || '';
    const path = wiring.poster_add_path || '/api/webhooks/poster/add';
    const secretUrl = useMemo(
        () => (secret ? buildPosterAddUrl(path, secret) : ''),
        [path, secret]
    );
    const headerValue = secret ? `X-Webhook-Secret: ${secret}` : '';
    const maskedSecret = secret ? '•'.repeat(Math.min(secret.length, 16)) : '';

    const copy = async (value, label) => {
        if (!value) return;
        try {
            await copyText(value);
            toast.success(`${label} copied`);
        } catch {
            toast.error(`Failed to copy ${label.toLowerCase()}`);
        }
    };

    return (
        <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center gap-2 px-5 py-3.5 text-left hover:bg-row-hover transition-colors"
            >
                <span
                    className="material-symbols-outlined text-[18px] text-fg-subtle transition-transform"
                    style={{ transform: open ? 'rotate(90deg)' : 'none' }}
                    aria-hidden="true"
                >
                    chevron_right
                </span>
                <span className="font-display text-[15px] font-semibold text-fg">
                    Setup &amp; secret
                </span>
                <span
                    className={`ml-auto font-mono text-[11px] px-2.5 py-[3px] rounded-full ${
                        secretConfigured
                            ? 'bg-success/15 text-success'
                            : 'bg-warning/15 text-warning'
                    }`}
                >
                    {secretConfigured ? 'authenticated' : 'unauthenticated'}
                </span>
            </button>

            {open && (
                <div className="px-5 pb-5 flex flex-col gap-4 border-t border-border-light">
                    <p className="text-sm text-fg-muted mt-4">
                        Point Sonarr / Radarr / Tautulli at the base URL to rename and push posters
                        the moment a new item lands — the same pipeline a scheduled poster_renamerr
                        run uses (rename → border replacer → Plex upload), scoped to the single item
                        in the payload.
                    </p>

                    {secretConfigured ? (
                        <div className="flex flex-col gap-3 p-3 rounded-lg border border-border bg-surface-inset">
                            <div className="flex items-center justify-between">
                                <span className="font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                    Shared secret
                                </span>
                                <button
                                    type="button"
                                    className="text-xs text-accent hover:underline"
                                    onClick={() => setRevealSecret(r => !r)}
                                >
                                    {revealSecret ? 'Hide' : 'Reveal'}
                                </button>
                            </div>
                            <div className="flex flex-col gap-1.5">
                                <span className="text-xs text-fg-muted">
                                    Preferred — header (Sonarr/Radarr &quot;Headers&quot; field):
                                </span>
                                <div className="flex items-center gap-2 p-2 rounded bg-surface font-mono text-xs break-all">
                                    <span className="flex-1">
                                        {revealSecret
                                            ? headerValue
                                            : `X-Webhook-Secret: ${maskedSecret}`}
                                    </span>
                                    <IconButton
                                        icon="content_copy"
                                        aria-label="Copy header"
                                        variant="ghost"
                                        size="small"
                                        onClick={() => copy(headerValue, 'Header')}
                                    />
                                </div>
                            </div>
                            <div className="flex flex-col gap-1.5">
                                <span className="text-xs text-fg-muted">
                                    Fallback — URL with{' '}
                                    <code className="text-accent">?secret=</code> query param (for
                                    services that can&apos;t send custom headers, e.g. Tautulli):
                                </span>
                                <div className="flex items-center gap-2 p-2 rounded bg-surface font-mono text-xs break-all">
                                    <span className="flex-1">
                                        {revealSecret
                                            ? secretUrl
                                            : `${buildPosterAddUrl(path, '')}?secret=${maskedSecret}`}
                                    </span>
                                    <IconButton
                                        icon="content_copy"
                                        aria-label="Copy secret URL"
                                        variant="ghost"
                                        size="small"
                                        onClick={() => copy(secretUrl, 'Secret URL')}
                                    />
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="p-3 rounded-lg border border-warning/30 bg-warning/10 text-sm text-fg">
                            <strong>No webhook secret configured.</strong> Any caller that can reach
                            this URL can enqueue a poster job. Fine on a trusted LAN; set{' '}
                            <code>general.webhook_secret</code> on the{' '}
                            <Link className="text-accent hover:underline" to="/settings/general">
                                General Settings
                            </Link>{' '}
                            page if you need authentication.
                        </div>
                    )}

                    <ul className="list-disc list-inside text-sm text-fg-muted space-y-1">
                        <li>
                            <strong>Sonarr:</strong> Settings → Connect → + → Webhook. Triggers:{' '}
                            <em>On File Import</em>, <em>On File Upgrade</em>,{' '}
                            <em>On Series Add</em> (<em>On Import Complete</em> also works — CHUB
                            de-duplicates it).
                        </li>
                        <li>
                            <strong>Radarr:</strong> Settings → Connect → + → Webhook. Triggers:{' '}
                            <em>On File Import</em>, <em>On File Upgrade</em>,{' '}
                            <em>On Movie Added</em>.
                        </li>
                        <li>
                            <strong>Tautulli:</strong> Settings → Notification Agents → Webhook.
                            Trigger: <em>Recently Added</em>. JSON format.
                        </li>
                        <li>
                            CHUB matches each webhook to the instance that sent it by the
                            caller&apos;s IP (a Docker service name like <code>sonarr</code> is
                            resolved automatically), so no extra setup is normally needed. Two
                            instances on the <em>same</em> IP but different ports are told apart by
                            the payload&apos;s instance name, so give each Sonarr/Radarr a distinct{' '}
                            <em>Instance Name</em> (Settings → General).
                        </li>
                        <li>
                            <strong>Behind a reverse proxy</strong> (Traefik/nginx/Caddy) the
                            caller&apos;s IP is the proxy&apos;s. CHUB honors{' '}
                            <code>X-Forwarded-For</code> from any LAN/Docker proxy by default (the{' '}
                            <em>Trusted proxies</em> setting on{' '}
                            <Link className="text-accent hover:underline" to="/settings/general">
                                General
                            </Link>
                            ), so IP matching still works — no need to bypass the proxy. If it still
                            can&apos;t tell instances apart (host networking, identical names, or an
                            untrusted proxy), append <code>?instance=&lt;name&gt;</code> to the URL
                            (or send an <code>X-Chub-Instance</code> header) with the exact{' '}
                            <Link className="text-accent hover:underline" to="/settings/instances">
                                instance
                            </Link>{' '}
                            name to route it explicitly.
                        </li>
                        <li>
                            Per-instance <code>webhook_force_reupload</code> on the{' '}
                            <Link className="text-accent hover:underline" to="/settings/instances">
                                Instances
                            </Link>{' '}
                            page forces re-upload even when the poster hash is unchanged.
                        </li>
                    </ul>
                </div>
            )}
        </section>
    );
};

/** Status pill styling per provisioning state. */
const STATUS_META = {
    connected: { label: 'Connected', cls: 'bg-success/15 text-success' },
    drift: { label: 'Out of date', cls: 'bg-warning/15 text-warning' },
    not_set_up: { label: 'Not set up', cls: 'bg-surface-inset text-fg-muted' },
    failed: { label: 'Failed', cls: 'bg-error/15 text-error' },
    skipped: { label: 'Skipped', cls: 'bg-surface-inset text-fg-subtle' },
};

const TYPE_LABEL = { radarr: 'Radarr', sonarr: 'Sonarr', lidarr: 'Lidarr' };

/** Auto-provision the poster webhook into each Radarr/Sonarr via its own API —
 *  no manual "Settings → Connect → Webhook" per instance. Stateless: the arr's
 *  own notification list is the source of truth (dry-run status = read + diff). */
const AutoSetupBoard = () => {
    const toast = useToast();
    const [status, setStatus] = useState(null);
    const [baseUrl, setBaseUrl] = useState('');
    const [includeUpgrade, setIncludeUpgrade] = useState(false);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);

    // Handler-driven refresh (re-check / after a mutation). Never touches the
    // editable base-URL input, so it can't stomp a value the user is typing.
    const load = useCallback(async url => {
        setLoading(true);
        try {
            const origin = typeof window !== 'undefined' ? window.location.origin : '';
            const resp = await webhooksAPI.getProvisionStatus({
                baseUrl: url,
                originHint: origin,
            });
            setStatus(resp?.data || {});
        } catch {
            setStatus({
                instances: [],
                base_url_error: 'Could not load provisioning status.',
            });
        } finally {
            setLoading(false);
        }
    }, []);

    // Initial fetch. All setState runs in the async callbacks (not synchronously
    // in the effect body), and prefills the base-URL input exactly once.
    useEffect(() => {
        let active = true;
        const origin = typeof window !== 'undefined' ? window.location.origin : '';
        webhooksAPI
            .getProvisionStatus({ originHint: origin })
            .then(resp => {
                if (!active) return;
                const data = resp?.data || {};
                setStatus(data);
                setBaseUrl(prev => prev || data.base_url || origin || '');
                setLoading(false);
            })
            .catch(() => {
                if (!active) return;
                setStatus({
                    instances: [],
                    base_url_error: 'Could not load provisioning status.',
                });
                setLoading(false);
            });
        return () => {
            active = false;
        };
    }, []);

    const runProvision = async instances => {
        setBusy(true);
        try {
            const resp = await webhooksAPI.provision({ instances, baseUrl, includeUpgrade });
            const rows = resp?.data?.instances || [];
            const failed = rows.filter(r => r.status === 'failed');
            const wrote = rows.filter(r => ['created', 'updated'].includes(r.action)).length;
            if (failed.length) {
                toast.error(`${failed.length} instance(s) failed — see the rows below`);
            } else {
                toast.success(
                    wrote ? `Webhook set up on ${wrote} instance(s)` : 'Already up to date'
                );
            }
            await load(baseUrl);
        } catch {
            toast.error('Provisioning failed');
        } finally {
            setBusy(false);
        }
    };

    const runRemove = async instances => {
        setBusy(true);
        try {
            await webhooksAPI.removeProvision({ instances });
            toast.success('Webhook removed');
            await load(baseUrl);
        } catch {
            toast.error('Removal failed');
        } finally {
            setBusy(false);
        }
    };

    const instances = status?.instances || [];
    const driftNames = instances.filter(i => i.status === 'drift').map(i => i.name);
    const setupNames = instances
        .filter(i => ['not_set_up', 'drift', 'failed'].includes(i.status))
        .map(i => i.name);
    const disabled = busy || loading || !!status?.base_url_error;

    return (
        <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3">
                <h2 className="font-display text-[15px] font-semibold text-fg flex items-center gap-2.5">
                    <span className="material-symbols-outlined text-[18px] text-accent">bolt</span>
                    Auto-setup
                </h2>
                <div className="flex items-center gap-2">
                    {driftNames.length > 0 && (
                        <button
                            type="button"
                            disabled={disabled}
                            onClick={() => runProvision(driftNames)}
                            className="h-8 px-3 rounded-[7px] bg-warning/15 text-warning text-xs font-semibold hover:bg-warning/25 transition-colors disabled:opacity-50"
                        >
                            Fix all ({driftNames.length})
                        </button>
                    )}
                    <button
                        type="button"
                        disabled={disabled || setupNames.length === 0}
                        onClick={() => runProvision(['all'])}
                        className="h-8 px-3 rounded-[7px] bg-primary text-on-color text-xs font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
                    >
                        {busy ? 'Working…' : 'Set up webhooks'}
                    </button>
                    <IconButton
                        icon="refresh"
                        aria-label="Re-check provisioning status"
                        variant="ghost"
                        size="small"
                        disabled={busy}
                        onClick={() => load(baseUrl)}
                    />
                </div>
            </div>

            <p className="px-5 text-sm text-fg-muted">
                Let CHUB add its poster webhook to each Radarr/Sonarr for you — with the right
                instance routing (and secret) baked in. On File Import only.
            </p>

            {/* Base URL — must be reachable FROM the *arr containers */}
            <div className="px-5 pt-3 pb-1 flex flex-col gap-1.5">
                <label
                    htmlFor="chub-base-url"
                    className="font-mono text-[10px] uppercase tracking-wider text-fg-dim"
                >
                    CHUB base URL (as your *arrs reach it)
                </label>
                <input
                    id="chub-base-url"
                    type="text"
                    value={baseUrl}
                    onChange={e => setBaseUrl(e.target.value)}
                    placeholder="http://192.168.1.10:8060"
                    className="h-9 px-3 rounded-lg bg-surface-inset border border-border font-mono text-[13px] text-fg focus:border-accent outline-none"
                />
                <span className="text-[11.5px] text-fg-subtle">
                    {status?.public_url_configured
                        ? 'From your saved public_url. '
                        : status?.detected_base_url
                          ? 'Auto-detected from an existing webhook in your *arrs. '
                          : 'Auto-filled from your browser address. '}
                    It must be reachable <em>from your *arr containers</em> — behind a reverse proxy
                    that&apos;s usually a LAN IP or docker service name, not the public hostname.
                    Edit it here, then{' '}
                    <Link className="text-accent hover:underline" to="/settings/general">
                        save it on General
                    </Link>{' '}
                    to persist.
                </span>
                <label className="mt-1.5 flex items-center gap-2 text-[12.5px] text-fg-muted select-none">
                    <input
                        type="checkbox"
                        checked={includeUpgrade}
                        onChange={e => setIncludeUpgrade(e.target.checked)}
                        className="accent-accent"
                    />
                    Also trigger on file upgrade (usually unnecessary)
                </label>
            </div>

            {status?.base_url_error && (
                <div className="mx-5 mt-2 p-3 rounded-lg border border-warning/30 bg-warning/10 text-[13px] text-fg">
                    {status.base_url_error}
                </div>
            )}

            <div className="mt-3 overflow-x-auto">
                {loading && !status ? (
                    <p className="px-5 pb-5 text-sm text-fg-muted">Loading…</p>
                ) : instances.length === 0 ? (
                    <p className="px-5 pb-5 text-sm text-fg-muted">
                        No Radarr/Sonarr instances configured.
                    </p>
                ) : (
                    <table className="w-full text-sm">
                        <tbody>
                            {instances.map(inst => {
                                const meta = STATUS_META[inst.status] || STATUS_META.failed;
                                const canProvision = ['not_set_up', 'drift', 'failed'].includes(
                                    inst.status
                                );
                                const canRemove = ['connected', 'drift'].includes(inst.status);
                                return (
                                    <tr
                                        key={`${inst.type}-${inst.name}`}
                                        className="border-t border-border-light"
                                    >
                                        <td className="px-5 py-3 whitespace-nowrap">
                                            <span className="font-semibold text-fg">
                                                {inst.name}
                                            </span>
                                            <span className="ml-2 font-mono text-[10px] px-1.5 py-[2px] rounded bg-surface-inset text-fg-subtle">
                                                {TYPE_LABEL[inst.type] || inst.type}
                                            </span>
                                        </td>
                                        <td className="px-3 py-3">
                                            <span
                                                className={`font-mono text-[11px] px-2 py-[3px] rounded-full ${meta.cls}`}
                                            >
                                                {meta.label}
                                            </span>
                                            {(inst.error ||
                                                (inst.drift_fields || []).length > 0 ||
                                                inst.foreign_webhook) && (
                                                <div className="mt-1 text-[11.5px] text-fg-subtle max-w-[46ch]">
                                                    {inst.error ||
                                                        (inst.drift_fields?.length
                                                            ? `Stale: ${inst.drift_fields.join(', ')}`
                                                            : '')}
                                                    {inst.foreign_webhook && (
                                                        <span className="text-warning">
                                                            {' '}
                                                            (another webhook “{inst.foreign_webhook}
                                                            ” also targets CHUB — left untouched)
                                                        </span>
                                                    )}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-5 py-3 text-right whitespace-nowrap">
                                            {inst.status !== 'skipped' && (
                                                <div className="inline-flex gap-2">
                                                    {canProvision && (
                                                        <button
                                                            type="button"
                                                            disabled={disabled}
                                                            onClick={() =>
                                                                runProvision([inst.name])
                                                            }
                                                            className="text-xs text-accent hover:underline disabled:opacity-50"
                                                        >
                                                            {inst.status === 'drift'
                                                                ? 'Fix'
                                                                : 'Enable'}
                                                        </button>
                                                    )}
                                                    {canRemove && (
                                                        <button
                                                            type="button"
                                                            disabled={busy}
                                                            onClick={() => runRemove([inst.name])}
                                                            className="text-xs text-fg-subtle hover:text-error hover:underline disabled:opacity-50"
                                                        >
                                                            Remove
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </section>
    );
};

export const WebhooksPage = () => {
    const toast = useToast();

    const { data: wiringData, refresh: refreshWiring } = useApiData({
        apiFunction: webhooksAPI.getWiring,
        options: { showErrorToast: false },
    });

    const { data: originsData, refresh: refreshOrigins } = useApiData({
        apiFunction: useCallback(() => webhooksAPI.getWebhookOrigins(7), []),
        options: { showErrorToast: false },
    });

    const wiring = wiringData?.data || {};
    const origins = originsData?.data || {};
    const path = wiring.poster_add_path || '/api/webhooks/poster/add';
    const baseUrl = useMemo(() => buildPosterAddUrl(path, ''), [path]);
    const rows = origins.by_origin || [];

    const copyBase = async () => {
        try {
            await copyText(baseUrl);
            toast.success('Base URL copied');
        } catch {
            toast.error('Failed to copy URL');
        }
    };

    const handleRefreshAll = () => {
        refreshWiring();
        refreshOrigins();
        toast.success('Webhook status refreshed');
    };

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Webhooks
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Incoming hooks that let Radarr / Sonarr / Plex trigger CHUB modules.
                    </p>
                </div>
                <IconButton
                    icon="refresh"
                    aria-label="Refresh webhook status"
                    variant="ghost"
                    onClick={handleRefreshAll}
                />
            </div>

            {/* Unauthenticated-webhook banner — the ingest endpoints are
                auth-exempt and gated only by the optional shared secret. */}
            {wiringData?.data && !wiring.secret_configured && (
                <div
                    role="alert"
                    className="flex items-start gap-3 px-4 py-3.5 rounded-xl border border-warning/40 bg-warning/10"
                >
                    <span
                        className="material-symbols-outlined text-warning text-[20px] shrink-0 mt-0.5"
                        aria-hidden="true"
                    >
                        warning
                    </span>
                    <div className="text-[13.5px] text-fg leading-relaxed">
                        <strong className="text-warning">
                            Webhook endpoints are unauthenticated.
                        </strong>{' '}
                        No <code>general.webhook_secret</code> is set, so anyone who can reach{' '}
                        <code>/api/webhooks/*</code> can enqueue jobs. Fine on a trusted LAN — but
                        if CHUB is behind a reverse proxy or otherwise reachable off-LAN, set a
                        secret on the{' '}
                        <Link
                            className="text-accent hover:underline font-semibold"
                            to="/settings/general"
                        >
                            General Settings
                        </Link>{' '}
                        page and add it to your *arr webhook URLs.
                    </div>
                </div>
            )}

            {/* BASE URL strip */}
            <div className="flex items-center gap-3 px-4 py-3.5 rounded-xl bg-surface border border-border">
                <span className="font-mono text-[10px] tracking-wider text-fg-subtle shrink-0">
                    BASE URL
                </span>
                <span className="flex-1 min-w-0 font-mono text-[13px] text-fg-muted truncate">
                    {baseUrl}
                </span>
                <button
                    type="button"
                    onClick={copyBase}
                    className="flex items-center gap-1.5 h-8 px-3 rounded-[7px] bg-surface-inset border border-border text-accent text-xs font-semibold hover:bg-row-hover transition-colors shrink-0"
                >
                    <span className="material-symbols-outlined text-[14px]">content_copy</span>
                    Copy
                </button>
            </div>

            {/* AUTO-SETUP: provision the webhook into each *arr via its API */}
            <AutoSetupBoard />

            {/* RECENT CALLERS telemetry table */}
            <section className="bg-surface border border-border rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-5 pt-4 pb-3">
                    <h2 className="font-display text-[15px] font-semibold text-fg flex items-center gap-2.5">
                        <span
                            className="w-[7px] h-[7px] rounded-full bg-success"
                            aria-hidden="true"
                        />
                        Recent callers
                        <span className="font-mono text-[11px] font-normal text-fg-subtle">
                            last 7 days
                        </span>
                    </h2>
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh recent callers"
                        variant="ghost"
                        size="small"
                        onClick={refreshOrigins}
                    />
                </div>
                {rows.length === 0 ? (
                    <p className="px-5 pb-5 text-sm text-fg-muted">
                        No webhook calls in the last 7 days yet. Hit the test button in
                        Sonarr/Radarr after wiring it up.
                    </p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-y border-border text-left font-mono text-[10px] uppercase tracking-wider text-fg-dim">
                                    <th className="px-5 py-2.5 font-medium">Hook</th>
                                    <th className="px-3 py-2.5 font-medium">Triggers</th>
                                    <th className="px-3 py-2.5 font-medium">Origin</th>
                                    <th className="px-3 py-2.5 font-medium text-right">7d hits</th>
                                    <th className="px-3 py-2.5 font-medium text-right pr-5">
                                        Last
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.map((r, idx) => (
                                    <tr
                                        key={`${r.client_host}-${idx}`}
                                        className="border-b border-border-light last:border-0 hover:bg-row-hover transition-colors"
                                    >
                                        <td className="px-5 py-3 text-sm font-semibold text-fg whitespace-nowrap">
                                            {r.event_type || 'Poster on add'}
                                        </td>
                                        <td className="px-3 py-3">
                                            <span className="font-mono text-[11px] px-2 py-[3px] rounded-md bg-primary/14 text-source-cl2k">
                                                poster_renamerr
                                            </span>
                                        </td>
                                        <td className="px-3 py-3 font-mono text-[11.5px] text-fg-data">
                                            {r.client_host}
                                        </td>
                                        <td className="px-3 py-3 text-right font-mono text-[12px] text-fg-muted">
                                            {r.count}
                                        </td>
                                        <td className="px-3 py-3 pr-5 text-right font-mono text-[11.5px] text-fg-subtle whitespace-nowrap">
                                            {timeAgo(r.last_seen)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
                {origins.by_status && Object.keys(origins.by_status).length > 0 && (
                    <p className="px-5 py-3 border-t border-border-light font-mono text-[11px] text-fg-subtle">
                        Total {origins.total} ·{' '}
                        {Object.entries(origins.by_status)
                            .map(([s, c]) => `${s}: ${c}`)
                            .join(' · ')}
                    </p>
                )}
            </section>

            <SetupDetails wiring={wiring} />

            {/* Provenance footnote */}
            <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-border">
                <span
                    className="material-symbols-outlined text-fg-subtle text-[18px] shrink-0"
                    aria-hidden="true"
                >
                    info
                </span>
                <span className="text-[12.5px] text-fg-subtle">
                    Each hit is recorded as a job with its origin (client host + endpoint), so a
                    noisy or dead webhook shows up in{' '}
                    <Link to="/settings/jobs" className="text-accent hover:underline">
                        Jobs
                    </Link>
                    .
                </span>
            </div>
        </div>
    );
};

export default WebhooksPage;
