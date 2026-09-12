/** Guards the hourly minute clamp, the single synchronous emit, and the panel's label binding. */
import { StrictMode } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScheduleField } from './ScheduleField.jsx';

const field = { key: 'schedule', label: 'Schedule' };

describe('ScheduleField', () => {
    it.each([
        ['99', 'hourly(59)'],
        ['-5', 'hourly(0)'],
    ])('clamps a typed hourly minute of %s', (typed, expected) => {
        const onChange = vi.fn();
        render(<ScheduleField field={field} value="hourly(5)" onChange={onChange} />);

        fireEvent.change(screen.getByLabelText('Minute (0-59)'), { target: { value: typed } });
        expect(onChange).toHaveBeenLastCalledWith(expected);
    });

    it('emits once, synchronously, and nothing after unmount', async () => {
        const onChange = vi.fn();
        const { unmount } = render(
            <StrictMode>
                <ScheduleField field={field} value="hourly(5)" onChange={onChange} />
            </StrictMode>
        );

        fireEvent.change(screen.getByLabelText('Minute (0-59)'), { target: { value: '30' } });
        expect(onChange).toHaveBeenCalledTimes(1);
        expect(onChange).toHaveBeenCalledWith('hourly(30)');

        unmount();
        await new Promise(resolve => setTimeout(resolve, 10));
        expect(onChange).toHaveBeenCalledTimes(1);
    });

    it('binds the Time label to its input and names the daily times group', () => {
        const { unmount } = render(
            <ScheduleField field={field} value="weekly(monday@09:00)" onChange={() => {}} />
        );
        expect(screen.getByLabelText('Time')).toHaveValue('09:00');
        unmount();

        render(<ScheduleField field={field} value="daily(09:00|18:00)" onChange={() => {}} />);
        expect(screen.getByRole('group', { name: 'Daily Times' })).toBeInTheDocument();
    });

    it('names each daily time input by its position', () => {
        render(<ScheduleField field={field} value="daily(09:00|18:00)" onChange={() => {}} />);
        expect(screen.getByLabelText('Time 1')).toHaveValue('09:00');
        expect(screen.getByLabelText('Time 2')).toHaveValue('18:00');
    });
});
