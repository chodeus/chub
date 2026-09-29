/** Guards one border colour per state: Tailwind orders rival colour utilities by name, not by class order. */
import { render } from '@testing-library/react';
import { InputBase } from './InputBase.jsx';
import { SelectBase } from './SelectBase.jsx';
import { TextareaBase } from './TextareaBase.jsx';

const BORDER_COLOUR = /^border-(border|error|input-disabled)$/;

const fields = [
    ['InputBase', props => <InputBase id="f" value="" onChange={() => {}} {...props} />],
    [
        'SelectBase',
        props => <SelectBase id="f" value="" onChange={() => {}} options={[]} {...props} />,
    ],
    ['TextareaBase', props => <TextareaBase id="f" value="" onChange={() => {}} {...props} />],
];

const states = [
    ['default', 'border-border', {}],
    ['disabled', 'border-input-disabled', { disabled: true }],
    ['invalid', 'border-error', { invalid: true }],
    ['invalid and disabled', 'border-error', { invalid: true, disabled: true }],
];

describe.each(fields)('%s', (_name, Field) => {
    it.each(states)('%s gets only %s', (_state, expected, props) => {
        const { container } = render(<Field {...props} />);
        const control = container.querySelector('input, select, textarea');
        expect([...control.classList].filter(c => BORDER_COLOUR.test(c))).toEqual([expected]);
    });
});

it.each([
    [false, 'text-fg-muted'],
    [true, 'text-fg-subtle'],
])('SelectBase arrow with disabled=%s carries only %s', (disabled, expected) => {
    const { container } = render(
        <SelectBase id="f" value="" onChange={() => {}} options={[]} disabled={disabled} />
    );
    const arrow = container.querySelector('.material-symbols-outlined');
    expect([...arrow.classList].filter(c => c.startsWith('text-'))).toEqual([expected]);
});
