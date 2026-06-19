import React, { useMemo, useState, useCallback } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { webhooksAPI } from '../../utils/api/webhooks.js';
import { copyText } from '../../utils/clipboard.js';
import { Card } from '../../components/ui/card/Card.jsx';
import { IconButton, PageHeader } from '../../components/ui';

const buildPosterAddUrl = (path, secret) => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const base = `${origin}${path || '/api/webhooks/poster/add'}`;
    if (!secret) return base;
    return `${base}?secret=${encodeURIComponent(secret)}`;
};

const PosterAddCard = ({ wiringData, originsData, onRefresh }) => {
    const toast = useToast();
    const [revealSecret, setRevealSecret] = useState(false);

    const wiring = wiringData?.data || {};
    const origins = originsData?.data || {};
    const secretConfigured = !!wiring.secret_configured;
    const secret = wiring.secret || '';
    const path = wiring.poster_add_path || '/api/webhooks/poster/add';

    const plainUrl = useMemo(() => buildPosterAddUrl(path, ''), [path]);
    const secretUrl = useMemo(
        () => (secret ? buildPosterAddUrl(path, secret) : ''),
        [path, secret]
    );

    const handleCopy = useCallback(
        async (value, label) => {
            if (!value) return;
            try {
                await copyText(value);
                toast.success(`${label} copied`);
            } catch {
                toast.error(`Failed to copy ${label.toLowerCase()}`);
            }
        },
        [toast]
    );

    const headerValue = secret ? `X-Webhook-Secret: ${secret}` : '';
    const maskedSecret = secret ? '•'.repeat(Math.min(secret.length, 16)) : '';

    return (
        <Card variant="bordered">
            <Card.Body>
                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-brand-primary">
                                add_photo_alternate
                            </span>
                            <h3 className="text-lg font-semibold text-primary">
                                Poster on Media Add
                            </h3>
                        </div>
                        <span
                            className={`text-xs px-2 py-1 rounded-full font-medium ${
                                secretConfigured
                                    ? 'bg-success/15 text-success'
                                    : 'bg-warning/15 text-warning'
                            }`}
                        >
                            {secretConfigured ? 'authenticated' : 'unauthenticated'}
                        </span>
                    </div>

                    <p className="text-sm text-secondary">
                        Point Sonarr / Radarr / Tautulli at this URL to rename and push posters the
                        moment a new item lands — same pipeline a scheduled poster_renamerr run uses
                        (rename → border replacer → Plex upload), scoped to the single item in the
                        payload.
                    </p>

                    <div className="flex flex-col gap-2">
                        <span className="text-xs uppercase tracking-wide text-secondary">
                            Webhook URL
                        </span>
                        <div className="flex items-center gap-2 p-2 rounded bg-surface-alt font-mono text-sm break-all">
                            <span className="flex-1">{plainUrl}</span>
                            <IconButton
                                icon="content_copy"
                                aria-label="Copy webhook URL"
                                variant="ghost"
                                onClick={() => handleCopy(plainUrl, 'Webhook URL')}
                            />
                        </div>
                    </div>

                    {secretConfigured && (
                        <div className="flex flex-col gap-3 p-3 rounded border border-default bg-surface-alt">
                            <div className="flex items-center justify-between">
                                <span className="text-xs uppercase tracking-wide text-secondary">
                                    Shared secret
                                </span>
                                <button
                                    type="button"
                                    className="text-xs text-brand-primary hover:underline"
                                    onClick={() => setRevealSecret(r => !r)}
                                >
                                    {revealSecret ? 'Hide' : 'Reveal'}
                                </button>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-secondary">
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
                                        onClick={() => handleCopy(headerValue, 'Header')}
                                    />
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <span className="text-xs text-secondary">
                                    Fallback — URL with{' '}
                                    <code className="text-brand-primary">?secret=</code> query param
                                    (for services that can&apos;t send custom headers, e.g.
                                    Tautulli):
                                </span>
                                <div className="flex items-center gap-2 p-2 rounded bg-surface font-mono text-xs break-all">
                                    <span className="flex-1">
                                        {revealSecret
                                            ? secretUrl
                                            : buildPosterAddUrl(path, maskedSecret)}
                                    </span>
                                    <IconButton
                                        icon="content_copy"
                                        aria-label="Copy secret URL"
                                        variant="ghost"
                                        onClick={() => handleCopy(secretUrl, 'Secret URL')}
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    {!secretConfigured && (
                        <div className="p-3 rounded border border-warning/30 bg-warning/10 text-sm text-primary">
                            <strong>No webhook secret configured.</strong> Any caller that can reach
                            this URL can enqueue a poster job. Fine on a trusted LAN; set{' '}
                            <code>general.webhook_secret</code> on the{' '}
                            <a
                                className="text-brand-primary hover:underline"
                                href="/settings/general"
                            >
                                General Settings
                            </a>{' '}
                            page if you need authentication.
                        </div>
                    )}

                    <div className="flex flex-col gap-2 text-sm">
                        <span className="text-xs uppercase tracking-wide text-secondary">
                            Wiring
                        </span>
                        <ul className="list-disc list-inside text-secondary space-y-1">
                            <li>
                                <strong>Sonarr:</strong> Settings → Connect → + → Webhook. Triggers:{' '}
                                <em>On Import</em>, <em>On Upgrade</em>, <em>On Series Add</em>.
                            </li>
                            <li>
                                <strong>Radarr:</strong> Settings → Connect → + → Webhook. Triggers:{' '}
                                <em>On Import</em>, <em>On Upgrade</em>, <em>On Movie Added</em>.
                            </li>
                            <li>
                                <strong>Tautulli:</strong> Settings → Notification Agents → Webhook.
                                Trigger: <em>Recently Added</em>. JSON format.
                            </li>
                            <li>
                                Per-instance <code>webhook_force_reupload</code> on the{' '}
                                <a
                                    className="text-brand-primary hover:underline"
                                    href="/settings/instances"
                                >
                                    Instances
                                </a>{' '}
                                page forces re-upload even when the poster hash is unchanged.
                            </li>
                        </ul>
                    </div>

                    <div className="flex flex-col gap-2">
                        <div className="flex items-center justify-between">
                            <span className="text-xs uppercase tracking-wide text-secondary">
                                Recent callers (last 7d)
                            </span>
                            <IconButton
                                icon="refresh"
                                aria-label="Refresh recent callers"
                                variant="ghost"
                                size="small"
                                onClick={onRefresh}
                            />
                        </div>
                        {!origins.by_origin || origins.by_origin.length === 0 ? (
                            <p className="text-sm text-secondary italic">
                                No webhook jobs in the last 7 days yet. Hit the test button in
                                Sonarr/Radarr after wiring it up.
                            </p>
                        ) : (
                            <div className="flex flex-col gap-1">
                                {origins.by_origin.slice(0, 5).map((row, idx) => (
                                    <div
                                        key={`${row.client_host}-${row.endpoint}-${idx}`}
                                        className="flex items-center justify-between p-2 rounded bg-surface-alt text-sm"
                                    >
                                        <span className="font-mono text-xs text-primary">
                                            {row.client_host}{' '}
                                            <span className="text-secondary">→ {row.endpoint}</span>
                                        </span>
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-primary/15 text-brand-primary font-medium">
                                            {row.count}
                                        </span>
                                    </div>
                                ))}
                                {origins.by_status && (
                                    <p className="text-xs text-secondary mt-1">
                                        Total: {origins.total} ·{' '}
                                        {Object.entries(origins.by_status)
                                            .map(([s, c]) => `${s}: ${c}`)
                                            .join(' · ')}
                                    </p>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </Card.Body>
        </Card>
    );
};

export const WebhooksPage = () => {
    const toast = useToast();

    const { data: wiringData, refresh: refreshWiring } = useApiData({
        apiFunction: webhooksAPI.getWiring,
        options: { showErrorToast: false },
    });

    const { data: originsData, refresh: refreshOrigins } = useApiData({
        apiFunction: () => webhooksAPI.getWebhookOrigins(7),
        options: { showErrorToast: false },
    });

    const handleRefreshAll = () => {
        refreshWiring();
        refreshOrigins();
        toast.success('Webhook status refreshed');
    };

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Webhooks"
                description="Wire Sonarr / Radarr / Tautulli to push posters the moment new media lands."
                icon="webhook"
                actions={
                    <IconButton
                        icon="refresh"
                        aria-label="Refresh webhook status"
                        variant="ghost"
                        onClick={handleRefreshAll}
                    />
                }
            />

            <PosterAddCard
                wiringData={wiringData}
                originsData={originsData}
                onRefresh={refreshOrigins}
            />
        </div>
    );
};

export default WebhooksPage;
