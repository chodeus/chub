/** Guards pressed state on the schedule pills, the summary and month-day text, and cron a11y. */
import { render, screen } from '@testing-library/react';
import {
    PillSelector,
    WeekdaySelector,
    MonthdaySelector,
    ScheduleSummary,
    CronInput,
} from './index.js';

const pressedText = () =>
    screen.getAllByRole('button', { pressed: true }).map(button => button.textContent);

describe('schedule pills', () => {
    it('exposes the selected schedule type as pressed', () => {
        render(
            <PillSelector
                options={[
                    { type: 'hourly', label: 'Hourly' },
                    { type: 'daily', label: 'Daily' },
                ]}
                selectedType="daily"
                onTypeChange={() => {}}
            />
        );
        expect(pressedText()).toEqual(['Daily']);
        expect(screen.getByRole('button', { name: 'Hourly', pressed: false })).toBeInTheDocument();
    });

    it('exposes the selected weekdays as pressed', () => {
        render(<WeekdaySelector selectedDays={['monday']} onDaysChange={() => {}} />);
        expect(pressedText()).toEqual(['MondayMon', 'Mon']);
    });

    it('exposes the selected month days as pressed', () => {
        render(<MonthdaySelector selectedDays={[1, 15]} onDaysChange={() => {}} />);
        expect(pressedText()).toEqual(['1', '15']);
    });
});

describe('MonthdaySelector', () => {
    it('lists every selected day without a false "(and more)"', () => {
        render(<MonthdaySelector selectedDays={[1, 2, 3, 4, 5, 6, 7]} onDaysChange={() => {}} />);
        expect(screen.getByText('Selected: 1, 2, 3, 4, 5, 6, 7')).toBeInTheDocument();
    });
});

describe('ScheduleSummary', () => {
    it('never renders "undefined" for unrecognised weekly days', () => {
        render(
            <ScheduleSummary
                scheduleType="weekly"
                scheduleValue={{ days: ['someday'], time: '09:00' }}
            />
        );
        expect(screen.getByText('Weekly at 09:00 (no days specified)')).toBeInTheDocument();
    });
});

describe('CronInput', () => {
    it('labels the input and links it to its error', () => {
        render(<CronInput value="not a cron" onChange={() => {}} />);
        const input = screen.getByLabelText('Cron Expression');

        expect(input).toHaveAttribute('aria-invalid', 'true');
        expect(input).toHaveAccessibleDescription(/Invalid cron expression/);
    });
});
