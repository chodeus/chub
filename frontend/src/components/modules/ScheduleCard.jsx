import React, { useCallback } from 'react';
import PropTypes from 'prop-types';
import { scheduleToHuman } from '../../utils/schedule';
import { Button } from '../ui/button/Button';

/**
 * ScheduleCard — full-width module schedule row: name + human/cron line, the
 * raw schedule expression, run/cancel/test/edit controls, and per-instance
 * sub-schedule rows.
 */
export const ScheduleCard = React.memo(
    ({
        moduleKey,
        moduleLabel,
        schedule,
        subSchedules = [],
        isRunning = false,
        onRun,
        onEdit,
        onCancel,
        onTest,
    }) => {
        const hasSchedule = !!schedule;

        const handleEditClick = useCallback(
            e => {
                e.stopPropagation();
                onEdit(moduleKey, hasSchedule);
            },
            [moduleKey, hasSchedule, onEdit]
        );
        const handleRunClick = useCallback(
            e => {
                e.stopPropagation();
                if (!isRunning) onRun(moduleKey);
            },
            [moduleKey, isRunning, onRun]
        );
        const handleCancelClick = useCallback(
            e => {
                e.stopPropagation();
                if (onCancel) onCancel(moduleKey);
            },
            [moduleKey, onCancel]
        );
        const handleTestClick = useCallback(
            e => {
                e.stopPropagation();
                if (onTest) onTest(moduleKey);
            },
            [moduleKey, onTest]
        );

        const iconBtn =
            'w-8 h-8 rounded-lg flex items-center justify-center text-fg-muted hover:text-fg hover:bg-row-hover transition-colors';

        return (
            <div
                className="bg-surface border border-border rounded-xl overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                <div className="flex items-center gap-4 px-[18px] py-[15px]">
                    <div className="w-[200px] shrink-0 min-w-0">
                        <div className="font-display text-[15px] font-semibold text-fg truncate">
                            {moduleLabel}
                        </div>
                        <div
                            className={`font-mono text-[10.5px] mt-0.5 truncate ${
                                hasSchedule ? 'text-fg-subtle' : 'text-fg-faint'
                            }`}
                        >
                            {hasSchedule ? scheduleToHuman(schedule) : 'manual only'}
                        </div>
                    </div>

                    <div className="flex-1 min-w-0">
                        {hasSchedule ? (
                            <span className="font-mono text-[11px] text-fg-faint truncate">
                                {schedule}
                            </span>
                        ) : (
                            <span className="font-mono text-[12px] text-fg-dim">—</span>
                        )}
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                        {onTest && !isRunning && (
                            <button
                                type="button"
                                onClick={handleTestClick}
                                className="h-[30px] px-3 rounded-[7px] bg-surface-inset border border-border text-fg-muted text-xs font-semibold hover:bg-row-hover transition-colors"
                            >
                                Test
                            </button>
                        )}
                        {isRunning && onCancel && (
                            <Button variant="danger" size="small" onClick={handleCancelClick}>
                                Cancel
                            </Button>
                        )}
                        <Button
                            variant={isRunning ? 'surface' : 'primary'}
                            size="small"
                            onClick={handleRunClick}
                            disabled={isRunning}
                        >
                            {isRunning ? 'Running…' : 'Run'}
                        </Button>
                        <button
                            type="button"
                            onClick={handleEditClick}
                            className={iconBtn}
                            aria-label="Edit schedule"
                            title="Edit schedule"
                        >
                            <span className="material-symbols-outlined text-[18px]">edit</span>
                        </button>
                    </div>
                </div>

                {subSchedules.length > 0 && (
                    <div
                        className="bg-surface-inset border-t border-border-light"
                        style={{ boxShadow: 'inset 3px 0 0 var(--primary)' }}
                    >
                        {subSchedules.map(sub => (
                            <div
                                key={sub.label}
                                className={`flex items-center gap-3 px-[18px] py-2.5 border-b border-border-light last:border-b-0 ${
                                    sub.enabled ? '' : 'opacity-50'
                                }`}
                            >
                                <span
                                    className="w-1.5 h-1.5 rounded-full shrink-0"
                                    style={{ background: 'var(--source-gdrive)' }}
                                    aria-hidden="true"
                                />
                                <span className="text-[12.5px] font-medium text-fg-muted truncate flex-1 min-w-0">
                                    {sub.label}
                                </span>
                                <span
                                    className="shrink-0 font-mono text-[8px] uppercase tracking-[0.4px] px-1.5 py-px rounded-[4px]"
                                    style={{
                                        color: 'var(--source-gdrive)',
                                        background: 'rgba(83,232,240,.14)',
                                    }}
                                >
                                    profile
                                </span>
                                <span className="font-mono text-[11.5px] text-fg-data shrink-0">
                                    {sub.enabled ? scheduleToHuman(sub.schedule) : 'paused'}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }
);

ScheduleCard.displayName = 'ScheduleCard';

ScheduleCard.propTypes = {
    moduleKey: PropTypes.string.isRequired,
    moduleLabel: PropTypes.string.isRequired,
    schedule: PropTypes.string,
    subSchedules: PropTypes.arrayOf(
        PropTypes.shape({
            label: PropTypes.string,
            schedule: PropTypes.string,
            enabled: PropTypes.bool,
        })
    ),
    isRunning: PropTypes.bool,
    onRun: PropTypes.func.isRequired,
    onEdit: PropTypes.func.isRequired,
    onCancel: PropTypes.func,
    onTest: PropTypes.func,
};

export default ScheduleCard;
