/** Guards that an omitted initialValues does not reset typed values on a parent re-render. */
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Fails the test when a render loop exceeds the expected bound.
const h = vi.hoisted(() => ({ renders: 0 }));

vi.mock('../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }),
}));

vi.mock('./validation.js', () => ({
    validateField: () => null,
    validateForm: () => ({}),
}));

// Minimal stand-in for the registry: one text field that reports its value up.
vi.mock('../../components/fields/FieldRegistry.jsx', () => ({
    default: {
        getField:
            () =>
            ({ field, value, onChange }) => {
                if (++h.renders > 50) {
                    throw new Error(`render loop: field rendered ${h.renders} times`);
                }
                return (
                    <input
                        aria-label={field.key}
                        value={value ?? ''}
                        onChange={e => onChange(e.target.value)}
                    />
                );
            },
    },
}));

const { FormRenderer } = await import('./FormRenderer.jsx');

const schema = { fields: [{ key: 'name', type: 'text', label: 'Name' }] };

// initialValues is deliberately OMITTED, which is the defaulted path under test.
function Parent() {
    const [tick, setTick] = useState(0);
    return (
        <div>
            <button type="button" onClick={() => setTick(t => t + 1)}>
                rerender {tick}
            </button>
            <FormRenderer schema={schema} showSubmit={false} onChange={() => undefined} />
        </div>
    );
}

describe('FormRenderer with no initialValues', () => {
    beforeEach(() => {
        h.renders = 0;
    });

    it('keeps a typed value when the parent re-renders', () => {
        render(<Parent />);

        fireEvent.change(screen.getByLabelText('name'), { target: { value: 'cleanarr' } });
        expect(screen.getByLabelText('name')).toHaveValue('cleanarr');

        fireEvent.click(screen.getByRole('button', { name: /rerender/ }));

        expect(screen.getByLabelText('name')).toHaveValue('cleanarr');
    });
});
