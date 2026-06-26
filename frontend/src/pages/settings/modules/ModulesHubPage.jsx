import React, { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../../hooks/useApiData.js';
import { useToast } from '../../../contexts/ToastContext.jsx';
import { configAPI } from '../../../utils/api/config.js';
import { scheduleAPI } from '../../../utils/api/schedule.js';
import { moduleOrder } from '../../../utils/constants/constants.js';
import { SETTINGS_MODULES } from '../../../utils/constants/settings_schema.js';
import { humanize } from '../../../utils/tools.js';
import Toggle from '../../../components/ui/Toggle.jsx';
import Spinner from '../../../components/ui/Spinner.jsx';

// Runnable modules in display order — drop the non-module config sections.
const HUB_MODULES = moduleOrder.filter(k => k !== 'general' && k !== 'main');

// name + description per module key (from the shared settings metadata).
const META = SETTINGS_MODULES.reduce((acc, m) => {
    acc[m.key] = { name: m.name || humanize(m.key), description: m.description || '' };
    return acc;
}, {});

const MODULE_ICONS = {
    sync_gdrive: 'cloud_sync',
    poster_renamerr: 'drive_file_rename_outline',
    asset_renamerr: 'wallpaper',
    poster_cleanarr: 'cleaning_services',
    plex_maintenance: 'build',
    border_replacerr: 'border_style',
    unmatched_assets: 'image_search',
    renameinatorr: 'edit_note',
    upgradinatorr: 'upgrade',
    nohl: 'link_off',
    nestarr: 'move_to_inbox',
    labelarr: 'label',
    health_checkarr: 'health_and_safety',
    jduparr: 'difference',
};

// Rotating icon tints (mock palette: cyan / green / lilac / gold / peach).
const TINTS = [
    ['#53e8f0', 'rgba(83,232,240,.12)'],
    ['#6cbc66', 'rgba(108,188,102,.12)'],
    ['#a99eff', 'rgba(169,158,255,.14)'],
    ['#ffc944', 'rgba(255,201,68,.12)'],
    ['#ff9d75', 'rgba(255,157,117,.12)'],
];

/** Friendly schedule pill label derived from the schedule DSL. */
const schedLabel = dsl => {
    if (!dsl) return 'Manual';
    const s = String(dsl).toLowerCase();
    if (s.includes('cron(')) return 'Cron';
    if (s.includes('range(')) return 'Seasonal';
    if (s.includes('daily')) return 'Daily';
    if (s.includes('weekly')) return 'Weekly';
    if (s.includes('hourly')) return 'Hourly';
    if (s.includes('monthly')) return 'Monthly';
    return 'Custom';
};

const SCHED_STYLE = {
    Manual: 'bg-surface-inset text-fg-data',
    Daily: 'bg-success/15 text-success',
    Weekly: 'bg-success/15 text-success',
    Hourly: 'bg-success/15 text-success',
    Monthly: 'bg-success/15 text-success',
    Cron: 'bg-primary/15 text-source-cl2k',
    Seasonal: 'bg-warning/15 text-warning',
    Custom: 'bg-accent/12 text-accent',
};

export const ModulesHubPage = () => {
    const toast = useToast();

    const {
        data: generalData,
        isLoading: generalLoading,
        refresh: refreshGeneral,
    } = useApiData({
        apiFunction: useCallback(() => configAPI.fetchSection('general'), []),
        options: { showErrorToast: false },
    });

    const { data: scheduleData } = useApiData({
        apiFunction: scheduleAPI.fetchSchedules,
        options: { showErrorToast: false },
    });

    const schedule = useMemo(() => scheduleData?.data?.schedule || {}, [scheduleData]);
    const savedDisabled = useMemo(
        () => generalData?.data?.general?.disabled_modules || [],
        [generalData]
    );

    // Optimistic local copy so toggles feel instant; null until first edit.
    const [override, setOverride] = useState(null);
    const [busyKey, setBusyKey] = useState(null);
    const disabled = override ?? savedDisabled;
    const disabledSet = useMemo(() => new Set(disabled), [disabled]);

    const enabledCount = HUB_MODULES.length - HUB_MODULES.filter(k => disabledSet.has(k)).length;

    const toggleModule = useCallback(
        async key => {
            const next = disabledSet.has(key)
                ? disabled.filter(k => k !== key)
                : [...disabled, key];
            setOverride(next);
            setBusyKey(key);
            try {
                await configAPI.updateConfig({ general: { disabled_modules: next } });
                refreshGeneral();
            } catch {
                toast.error('Failed to update module');
                setOverride(disabled); // roll back
            } finally {
                setBusyKey(null);
            }
        },
        [disabled, disabledSet, refreshGeneral, toast]
    );

    if (generalLoading && !generalData) {
        return <Spinner size="large" text="Loading modules…" center />;
    }

    return (
        <div className="flex flex-col gap-5">
            <div className="min-w-0">
                <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                    Modules
                </h1>
                <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                    Enable the chores you want and open each module&apos;s config ·{' '}
                    <span className="text-success">
                        {enabledCount} of {HUB_MODULES.length} enabled
                    </span>
                </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {HUB_MODULES.map((key, i) => {
                    const meta = META[key] || { name: humanize(key), description: '' };
                    const [iconColor, iconBg] = TINTS[i % TINTS.length];
                    const label = schedLabel(schedule[key]);
                    const enabled = !disabledSet.has(key);
                    return (
                        <div
                            key={key}
                            className={`flex items-center gap-3.5 px-4 py-[15px] rounded-xl bg-surface border transition-colors ${
                                enabled ? 'border-border' : 'border-border opacity-60'
                            }`}
                        >
                            <span
                                className="shrink-0 w-[38px] h-[38px] rounded-[9px] flex items-center justify-center"
                                style={{ background: iconBg, color: iconColor }}
                                aria-hidden="true"
                            >
                                <span className="material-symbols-outlined text-[20px]">
                                    {MODULE_ICONS[key] || 'tune'}
                                </span>
                            </span>

                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2.5">
                                    <span className="font-display text-[14.5px] font-semibold text-fg truncate">
                                        {meta.name}
                                    </span>
                                    <span
                                        className={`shrink-0 font-mono text-[9px] px-1.5 py-0.5 rounded-[5px] ${SCHED_STYLE[label]}`}
                                    >
                                        {label}
                                    </span>
                                </div>
                                <div className="text-xs text-fg-subtle mt-1 truncate">
                                    {meta.description}
                                </div>
                            </div>

                            <Link
                                to={`/settings/modules/${key}`}
                                className="shrink-0 font-mono text-[11px] text-accent hover:underline"
                            >
                                Configure
                            </Link>
                            <Toggle
                                label={`${meta.name} enabled`}
                                checked={enabled}
                                disabled={busyKey === key}
                                onChange={() => toggleModule(key)}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default ModulesHubPage;
