/**
 * Schedule Utilities
 * Provides schedule parsing, validation, and human-readable formatting
 */

import cronstrue from 'cronstrue/i18n';
import { isValidCron } from 'cron-validator';

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
        const entries = data.split('|').map(p => {
            const [day, time] = p.split('@');
            const [h, m] = time.split(':').map(Number);
            return { day: parseInt(day, 10), h, m };
        });
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
        const entries = data.split('|').map(p => {
            const [day, time] = p.split('@');
            const [h, m] = time.split(':').map(Number);
            return { day: parseInt(day, 10), h, m };
        });
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
                return /^\d{1,2}$/.test(data);
            case 'daily':
                return /^(\d{1,2}:\d{2}(\|\d{1,2}:\d{2})*)$/.test(data);
            case 'weekly':
                return /^([0-6]@\d{1,2}:\d{2}(\|[0-6]@\d{1,2}:\d{2})*)$/.test(data);
            case 'monthly':
                return /^(\d{1,2}@\d{1,2}:\d{2}(\|\d{1,2}@\d{1,2}:\d{2})*)$/.test(data);
            default:
                return false;
        }
    } catch {
        return false;
    }
}
