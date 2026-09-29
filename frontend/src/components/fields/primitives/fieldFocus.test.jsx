/** Guards the focus cue: invalid fields recolour the global focus outline, and one focus colour applies per state. */
import { render } from '@testing-library/react';
import { InputBase } from './InputBase.jsx';
import { SelectBase } from './SelectBase.jsx';
import { TextareaBase } from './TextareaBase.jsx';
import { CronInput } from '../features/schedule/CronInput.jsx';

const fields = [
    ['InputBase', props => <InputBase id="f" value="" onChange={() => {}} {...props} />],
    [
        'SelectBase',
        props => <SelectBase id="f" value="" onChange={() => {}} options={[]} {...props} />,
    ],
    ['TextareaBase', props => <TextareaBase id="f" value="" onChange={() => {}} {...props} />],
];

const controlClasses = container => [
    ...container.querySelector('input, select, textarea').classList,
];

describe.each(fields)('%s', (_name, Field) => {
    it('recolours the focus outline only when invalid', () => {
        expect(controlClasses(render(<Field invalid />).container)).toContain(
            'focus-visible:outline-error'
        );
        expect(controlClasses(render(<Field />).container)).not.toContain(
            'focus-visible:outline-error'
        );
    });

    // The global :focus-visible outline is the cue; a ring colour with no ring width draws nothing.
    it('sets no ring colour', () => {
        const classes = controlClasses(render(<Field invalid />).container);
        expect(classes.filter(c => c.includes('ring-'))).toEqual([]);
    });
});

it.each([
    ['0 9 * * 1-5', 'focus:ring-primary', 'focus:border-primary'],
    ['not a cron', 'focus:ring-error', 'focus:border-error'],
])('CronInput "%s" gets only %s and %s on focus', (value, ring, border) => {
    const classes = controlClasses(
        render(<CronInput value={value} onChange={() => {}} />).container
    );
    expect(classes.filter(c => /^focus:ring-(?!\d)/.test(c))).toEqual([ring]);
    expect(classes.filter(c => c.startsWith('focus:border-'))).toEqual([border]);
});
