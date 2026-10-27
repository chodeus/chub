import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useCallback, useLayoutEffect, useState } from 'react';
import { useLatestRef } from './useLatestRef.js';
import { ConfirmProvider, useConfirm } from '../contexts/ConfirmContext.jsx';
import { UIStateProvider } from '../contexts/UIStateContext.jsx';

/** Models the discard-vs-save race; `readLatest` picks the fixed path (ref)
 *  over the buggy one (a baseline captured before the await). */
function DiscardHarness({ readLatest }) {
    const [baseline, setBaseline] = useState('saved-v1');
    const [value, setValue] = useState('edited');
    const confirm = useConfirm();
    const baselineRef = useLatestRef(baseline);

    const discard = useCallback(async () => {
        const ok = await confirm('Discard?');
        if (!ok) return;
        setValue(readLatest ? baselineRef.current : baseline);
    }, [confirm, baseline, baselineRef, readLatest]);

    return (
        <>
            <button onClick={discard}>discard</button>
            <button onClick={() => setBaseline('saved-v2')}>save</button>
            <output>{value}</output>
        </>
    );
}

const renderHarness = readLatest =>
    render(
        <UIStateProvider>
            <ConfirmProvider>
                <DiscardHarness readLatest={readLatest} />
            </ConfirmProvider>
        </UIStateProvider>
    );

/** Open the dialog, save behind it, then confirm the discard. */
const raceSaveAgainstDiscard = async user => {
    await user.click(screen.getByRole('button', { name: 'discard' }));
    await user.click(screen.getByRole('button', { name: 'save' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
};

describe('useLatestRef', () => {
    it('restores the baseline saved while the dialog was open', async () => {
        const user = userEvent.setup();
        renderHarness(true);

        await raceSaveAgainstDiscard(user);

        await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('saved-v2'));
    });

    // Guards the guard: without the ref the same sequence restores the stale
    // value, which is the data loss this hook exists to prevent.
    it('demonstrates the stale capture it replaces', async () => {
        const user = userEvent.setup();
        renderHarness(false);

        await raceSaveAgainstDiscard(user);

        await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('saved-v1'));
    });

    it('is a no-op when nothing changes behind the dialog', async () => {
        const user = userEvent.setup();
        renderHarness(true);

        await user.click(screen.getByRole('button', { name: 'discard' }));
        await user.click(screen.getByRole('button', { name: 'Confirm' }));

        await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('saved-v1'));
    });
});

describe('useLatestRef timing', () => {
    it('is current in the same commit, before any passive effect', () => {
        const seen = [];
        const Probe = ({ value }) => {
            const ref = useLatestRef(value);
            // Declared after the hook, so it runs after the hook's own effect in the same commit.
            useLayoutEffect(() => {
                seen.push(ref.current);
            }, [ref, value]);
            return null;
        };
        const { rerender } = render(<Probe value="a" />);
        rerender(<Probe value="b" />);

        expect(seen).toEqual(['a', 'b']);
    });
});
