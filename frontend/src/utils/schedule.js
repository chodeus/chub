/**
 * Schedule Utilities
 * Provides schedule parsing, validation, and human-readable formatting
 */

import cronstrue from 'cronstrue/i18n';
import { isValidCron } from 'cron-validator';

const WEEKDAY_INDEX = {
    0: 0,
    7: 0,
    sun: 0,
    sunday: 0,
    1: 1,
    mon: 1,
    monday: 1,
    2: 2,
    tue: 2,
    tues: 2,
    tuesday: 2,
    3: 3,
    wed: 3,
    wednesday: 3,
    4: 4,
    thu: 4,
    thur: 4,
    thurs: 4,
    thursday: 4,
    5: 5,
    fri: 5,
    friday: 5,
    6: 6,
    sat: 6,
    saturday: 6,
};

function parseTime(time) {
    const match = String(time || '').match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return null;
    const h = Number(match[1]);
    const m = Number(match[2]);
    if (h < 0 || h > 23 || m < 0 || m > 59) return null;
    return { h, m };
}

function parseWeeklyEntries(data) {
    const entries = [];
    String(data || '')
        .split('|')
        .filter(Boolean)
        .forEach(part => {
            const [rawDays, rawTime] = part.split('@');
            const time = parseTime(rawTime);
            if (!rawDays || !time) return;
            rawDays
                .split(',')
                .map(day => day.trim().toLowerCase())
                .forEach(day => {
                    if (Object.prototype.hasOwnProperty.call(WEEKDAY_INDEX, day)) {
                        entries.push({ day: WEEKDAY_INDEX[day], ...time });
                    }
                });
        });
    return entries;
}

function parseMonthlyEntries(data) {
    const entries = [];
    String(data || '')
        .split('|')
        .filter(Boolean)
        .forEach(part => {
            const [rawDays, rawTime] = part.split('@');
            const time = parseTime(rawTime);
            if (!rawDays || !time) return;
            rawDays
                .split(',')
                .map(day => Number(day.trim()))
                .filter(day => Number.isInteger(day) && day >= 1 && day <= 31)
                .forEach(day => entries.push({ day, ...time }));
        });
    return entries;
}

/**
 * Convert schedule string to human-readable format
 * @param {string} schedule - Schedule string from config
 * @returns {string} Human-readable schedule description
 */
export function scheduleToHuman(schedule) {
    if (!schedule || typeof schedule !== 'string') return 'Not scheduled';

    const matchHourly = schedule.match(/^hourly\((\d{1,2})\)$/);
    const matchDaily = schedule.match(/^daily\(([\d:|]+)\)$/);
    const matchWeekly = schedule.match(/^weekly\(([^)]+)\)$/);
    const matchMonthly = schedule.match(/^monthly\(([^)]+)\)$/);
    const matchCron = schedule.match(/^cron\(([^)]*)\)$/);

    if (matchHourly) {
        return `Hourly at minute ${parseInt(matchHourly[1], 10)}`;
    }
    if (matchDaily) {
        const times = matchDaily[1].split('|');
        if (times.length === 1) {
            return `Daily at ${times[0]}`;
        }
        return `Daily at ${times.join(', ')}`;
    }
    if (matchWeekly) {
        const parts = matchWeekly[1].split('|');
        const dayTimes = parts.map(part => {
            const [day, time] = part.split('@');
            return `${day} at ${time}`;
        });
        return `Weekly: ${dayTimes.join(', ')}`;
    }
    if (matchMonthly) {
        const parts = matchMonthly[1].split('|');
        const dayTimes = parts.map(part => {
            const [day, time] = part.split('@');
            return `${day} at ${time}`;
        });
        return `Monthly: ${dayTimes.join(', ')}`;
    }
    if (matchCron) {
        const expr = matchCron[1];
        if (!expr) return 'Custom cron (empty)';
        if (!isValidCron(expr, { seconds: true, allowBlankDay: true })) {
            return 'Invalid cron expression';
        }
        try {
            return `Cron: ${cronstrue.toString(expr)}`;
        } catch {
            return 'Cron: (unparseable)';
        }
    }

    return `Unknown: ${schedule}`;
}

/**
 * Parse schedule string into structured format
 * @param {string} schedule - Schedule string from config
 * @returns {Object|null} Parsed schedule object
 */
export function parseSchedule(schedule) {
    if (!schedule || typeof schedule !== 'string') return null;

    const match = schedule.match(/^(\w+)\(([^)]*)\)$/);
    if (!match) return null;

    const [, frequency, data] = match;

    return {
        frequency,
        data,
        human: scheduleToHuman(schedule),
    };
}

/**
 * Compute the next fire time for a schedule string.
 * Handles hourly/daily/weekly/monthly; returns null for cron (needs cron-parser)
 * and for unscheduled/invalid input.
 * @param {string} schedule
 * @param {Date} [from=new Date()]
 * @returns {Date|null}
 */
export function scheduleToNextFire(schedule, from = new Date()) {
    if (!validateSchedule(schedule)) return null;
    const match = schedule.match(/^(\w+)\(([^)]*)\)$/);
    if (!match) return null;
    const [, frequency, data] = match;
    const base = new Date(from.getTime());

    const atTime = (d, h, m) => {
        const t = new Date(d);
        t.setHours(h, m, 0, 0);
        return t;
    };

    if (frequency === 'hourly') {
        const minute = parseInt(data, 10);
        const next = new Date(base);
        next.setMinutes(minute, 0, 0);
        if (next <= base) next.setHours(next.getHours() + 1);
        return next;
    }
    if (frequency === 'daily') {
        const times = data.split('|').map(t => t.split(':').map(Number));
        const todays = times
            .map(([h, m]) => atTime(base, h, m))
            .filter(t => t > base)
            .sort((a, b) => a - b);
        if (todays.length) return todays[0];
        const [h, m] = times.sort(([a, b], [c, d]) => a - c || b - d)[0];
        const tomorrow = new Date(base);
        tomorrow.setDate(tomorrow.getDate() + 1);
        return atTime(tomorrow, h, m);
    }
    if (frequency === 'weekly') {
        const entries = parseWeeklyEntries(data);
        const candidates = [];
        for (let offset = 0; offset < 8; offset++) {
            const d = new Date(base);
            d.setDate(d.getDate() + offset);
            entries
                .filter(e => e.day === d.getDay())
                .forEach(e => {
                    const t = atTime(d, e.h, e.m);
                    if (t > base) candidates.push(t);
                });
        }
        candidates.sort((a, b) => a - b);
        return candidates[0] || null;
    }
    if (frequency === 'monthly') {
        const entries = parseMonthlyEntries(data);
        const candidates = [];
        for (let offset = 0; offset < 2; offset++) {
            const month = new Date(base.getFullYear(), base.getMonth() + offset, 1);
            entries.forEach(e => {
                const t = atTime(new Date(month.getFullYear(), month.getMonth(), e.day), e.h, e.m);
                if (t > base) candidates.push(t);
            });
        }
        candidates.sort((a, b) => a - b);
        return candidates[0] || null;
    }
    return null;
}

/**
 * Format a future Date as "in 2h 14m" / "in 45m" / "in 12s".
 */
export function formatTimeUntil(target, from = new Date()) {
    if (!target) return '';
    const ms = target.getTime() - from.getTime();
    if (ms <= 0) return 'now';
    const totalSec = Math.floor(ms / 1000);
    const days = Math.floor(totalSec / 86400);
    const hours = Math.floor((totalSec % 86400) / 3600);
    const minutes = Math.floor((totalSec % 3600) / 60);
    if (days > 0) return `in ${days}d ${hours}h`;
    if (hours > 0) return `in ${hours}h ${minutes}m`;
    if (minutes > 0) return `in ${minutes}m`;
    return `in ${totalSec}s`;
}

/**
 * Format a past Date as "12m ago" / "2h ago" / "3d ago".
 */
export function formatTimeAgo(target, from = new Date()) {
    if (!target) return '';
    const t = target instanceof Date ? target : new Date(target);
    const ms = from.getTime() - t.getTime();
    if (ms < 0) return formatTimeUntil(t, from);
    const totalSec = Math.floor(ms / 1000);
    if (totalSec < 60) return 'just now';
    const minutes = Math.floor(totalSec / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return t.toLocaleDateString();
}

/**
 * Format an elapsed duration (in seconds) as "12m ago" / "2h ago" / "3d ago".
 * Wraps formatTimeAgo so callers that only have an age (not a timestamp) don't
 * have to do time math during render.
 */
export function formatSecondsAgo(seconds) {
    if (seconds == null || Number.isNaN(seconds)) return '';
    return formatTimeAgo(new Date(Date.now() - seconds * 1000));
}

/**
 * Validate schedule string format
 * @param {string} schedule - Schedule string to validate
 * @returns {boolean} True if valid schedule format
 */
export function validateSchedule(schedule) {
    if (!schedule || typeof schedule !== 'string') return false;

    try {
        const match = schedule.match(/^(\w+)\(([^)]*)\)$/);
        if (!match) return false;

        const [, frequency, data] = match;

        switch (frequency) {
            case 'cron':
                return isValidCron(data, { seconds: true, allowBlankDay: true });
            case 'hourly':
                return /^\d{1,2}$/.test(data) && Number(data) >= 0 && Number(data) <= 59;
            case 'daily': {
                const times = data.split('|').filter(Boolean);
                return times.length > 0 && times.every(time => parseTime(time));
            }
            case 'weekly':
                return parseWeeklyEntries(data).length > 0;
            case 'monthly':
                return parseMonthlyEntries(data).length > 0;
            default:
                return false;
        }
    } catch {
        return false;
    }
}
