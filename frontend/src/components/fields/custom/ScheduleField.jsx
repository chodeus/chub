import React, { useState, useCallback, useEffect, useRef } from 'react';
import { FieldWrapper, FieldLabel, FieldError, FieldDescription } from '../primitives';
import { PillSelector, ScheduleTypePanel, ScheduleSummary } from '../features/schedule';

// Schedule type options
const SCHEDULE_TYPES = [
    { type: 'hourly', label: 'Hourly' },
    { type: 'daily', label: 'Daily' },
    { type: 'weekly', label: 'Weekly' },
    { type: 'monthly', label: 'Monthly' },
    { type: 'cron', label: 'Cron' },
];

// Weekday mapping: backend format <-> frontend format
const DAY_ABBR_TO_KEY = {
    Sun: 'sunday',
    Mon: 'monday',
    Tue: 'tuesday',
    Wed: 'wednesday',
    Thu: 'thursday',
    Fri: 'friday',
    Sat: 'saturday',
};

const DAY_TOKEN_TO_KEY = {
    0: 'sunday',
    7: 'sunday',
    sun: 'sunday',
    sunday: 'sunday',
    1: 'monday',
    mon: 'monday',
    monday: 'monday',
    2: 'tuesday',
    tue: 'tuesday',
    tues: 'tuesday',
    tuesday: 'tuesday',
    3: 'wednesday',
    wed: 'wednesday',
    wednesday: 'wednesday',
    4: 'thursday',
    thu: 'thursday',
    thur: 'thursday',
    thurs: 'thursday',
    thursday: 'thursday',
    5: 'friday',
    fri: 'friday',
    friday: 'friday',
    6: 'saturday',
    sat: 'saturday',
    saturday: 'saturday',
};

// Compose schedule string from type and data
const composeScheduleString = (type, data) => {
    if (!type || !data) {
        return '';
    }

    try {
        switch (type) {
            case 'hourly': {
                const minute = data.minute ?? 0;
                return `hourly(${minute})`;
            }

            case 'daily': {
                const times = data.times || [];
                if (times.length === 0) return '';
                return `daily(${times.join('|')})`;
            }

            case 'weekly': {
                const days = data.days || [];
                const time = data.time || '09:00';
                if (days.length === 0) return '';
                return `weekly(${days.map(day => `${day}@${time}`).join('|')})`;
            }

            case 'monthly': {
                const days = data.days || [];
                const time = data.time || '09:00';
                if (days.length === 0) return '';
                return `monthly(${days.map(day => `${day}@${time}`).join('|')})`;
            }

            case 'cron': {
                const expression = data.expression || '';
                if (!expression.trim()) return 'cron()';
                return `cron(${expression})`;
            }

            default:
                return '';
        }
    } catch (error) {
        console.warn('Failed to compose schedule string:', type, data, error);
        return '';
    }
};

/**
 * Main schedule input component using atomic primitives
 * @param {Object} field - Field configuration
 * @param {string} value - Schedule string like "daily(14:30|18:00)" or "cron(0 9 * * 1-5)"
 * @param {Function} onChange - Value change handler
 * @param {boolean} disabled - Field disabled state
 * @param {boolean} highlightInvalid - Show validation errors
 * @param {string} errorMessage - Error message text
 */
export const ScheduleField = React.memo(
    ({
        field,
        value = '',
        onChange,
        disabled = false,
        highlightInvalid = false,
        errorMessage = null,
    }) => {
        const [scheduleType, setScheduleType] = useState('daily');
        const [scheduleData, setScheduleData] = useState({});
        // The data as queued: within a tick this leads committed state.
        const queuedData = useRef(scheduleData);

        // Parse incoming value into type and data
        const parseScheduleValue = useCallback(val => {
            if (!val || typeof val !== 'string') {
                return { type: 'daily', data: {} };
            }

            try {
                // Parse strings like "hourly(30)", "daily(09:00|17:00)", "cron(0 0 * * *)", "cron()"
                const match = val.match(/^(\w+)\((.*)\)$/);
                if (!match) {
                    return { type: 'daily', data: {} };
                }

                const [, type, dataStr] = match;

                switch (type) {
                    case 'hourly': {
                        const minute = parseInt(dataStr, 10);
                        return { type, data: { minute: isNaN(minute) ? 0 : minute } };
                    }

                    case 'daily': {
                        const times = dataStr.split('|').filter(Boolean);
                        return { type, data: { times } };
                    }

                    case 'weekly': {
                        // Accept both canonical "monday@09:00|friday@09:00"
                        // and older comma-list "Mon,Fri@09:00" values.
                        const entries = dataStr.split('|').filter(Boolean);
                        const days = [];
                        let time = '09:00';
                        entries.forEach(entry => {
                            const parts = entry.split('@');
                            if (parts.length === 2) {
                                parts[0]
                                    .split(',')
                                    .filter(Boolean)
                                    .forEach(day => {
                                        const token = day.trim().toLowerCase();
                                        const normalized =
                                            DAY_TOKEN_TO_KEY[token] ||
                                            DAY_ABBR_TO_KEY[day.trim()] ||
                                            token;
                                        if (!days.includes(normalized)) {
                                            days.push(normalized);
                                        }
                                    });
                                time = parts[1];
                            }
                        });
                        if (days.length > 0) {
                            return { type, data: { days, time } };
                        }
                        return { type, data: {} };
                    }

                    case 'monthly': {
                        // Accept both canonical "1@09:00|15@09:00"
                        // and older comma-list "1,15@09:00" values.
                        const entries = dataStr.split('|').filter(Boolean);
                        const days = [];
                        let time = '09:00';
                        entries.forEach(entry => {
                            const parts = entry.split('@');
                            if (parts.length === 2) {
                                parts[0]
                                    .split(',')
                                    .map(d => parseInt(d, 10))
                                    .filter(d => !isNaN(d))
                                    .forEach(day => {
                                        if (!days.includes(day)) {
                                            days.push(day);
                                        }
                                    });
                                time = parts[1];
                            }
                        });
                        if (days.length > 0) {
                            return { type, data: { days, time } };
                        }
                        return { type, data: {} };
                    }

                    case 'cron': {
                        return { type, data: { expression: dataStr } };
                    }

                    default:
                        return { type: 'daily', data: {} };
                }
            } catch (error) {
                console.warn('Failed to parse schedule value:', val, error);
                return { type: 'daily', data: {} };
            }
        }, []);

        // Sync from value on every change (not just type change), or a saved
        // schedule matching the 'daily' default never loads its data. Equality
        // guards prevent re-render loops.
        useEffect(() => {
            const parsed = parseScheduleValue(value);
            setScheduleType(prev => (prev === parsed.type ? prev : parsed.type));
            // Compare against the queued data, not committed state: an update made
            // earlier in this tick is not committed yet and must not be undone.
            if (JSON.stringify(queuedData.current) !== JSON.stringify(parsed.data)) {
                queuedData.current = parsed.data;
                setScheduleData(parsed.data);
            }
        }, [value, parseScheduleValue]);

        // Handle schedule type change
        const handleTypeChange = useCallback(
            newType => {
                if (newType === scheduleType) {
                    return; // Prevent unnecessary updates
                }
                setScheduleType(newType);

                // Reset data when switching types
                let newData = {};
                switch (newType) {
                    case 'hourly':
                        newData = { minute: 0 };
                        break;
                    case 'daily':
                        newData = { times: ['09:00'] };
                        break;
                    case 'weekly':
                        newData = { days: ['monday'], time: '09:00' };
                        break;
                    case 'monthly':
                        newData = { days: [1], time: '09:00' };
                        break;
                    case 'cron':
                        newData = { expression: '' };
                        break;
                }

                queuedData.current = newData;
                setScheduleData(newData);

                // Compose and emit new value
                const newValue = composeScheduleString(newType, newData);
                onChange(newValue);
            },
            [scheduleType, onChange]
        ); // Include scheduleType dependency

        // Handle schedule data change
        const handleDataChange = useCallback(
            newDataOrUpdater => {
                // Apply to the latest queued data: two updates in one tick would both
                // read the committed snapshot, and the first would be lost.
                const previous = queuedData.current;
                const updatedData =
                    typeof newDataOrUpdater === 'function'
                        ? newDataOrUpdater(previous)
                        : newDataOrUpdater;
                queuedData.current = updatedData;
                setScheduleData(updatedData);

                const newValue = composeScheduleString(scheduleType, updatedData);
                if (newValue !== composeScheduleString(scheduleType, previous)) {
                    onChange(newValue);
                }
            },
            [scheduleType, onChange]
        );

        const inputId = `field-${field.key}`;

        return (
            <FieldWrapper invalid={highlightInvalid}>
                <FieldLabel label={field.label} required={field.required} />

                <div className="space-y-4">
                    {/* Schedule type selector */}
                    <PillSelector
                        options={SCHEDULE_TYPES}
                        selectedType={scheduleType}
                        onTypeChange={handleTypeChange}
                        disabled={disabled}
                    />

                    {/* Dynamic content panel based on schedule type */}
                    <ScheduleTypePanel
                        scheduleType={scheduleType}
                        scheduleData={scheduleData}
                        onDataChange={handleDataChange}
                        disabled={disabled}
                    />

                    {/* Human-readable schedule summary */}
                    <ScheduleSummary
                        scheduleType={scheduleType}
                        scheduleValue={scheduleData}
                        cronExpression={scheduleType === 'cron' ? scheduleData.expression : ''}
                    />
                </div>

                <FieldDescription id={`${inputId}-desc`} description={field.description} />
                <FieldError id={`${inputId}-error`} message={errorMessage} />
            </FieldWrapper>
        );
    }
);

ScheduleField.displayName = 'ScheduleField';

export default ScheduleField;
