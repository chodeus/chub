/**
 * The Poster Healer "Assessed locations" settings strip.
 *
 * The registry assertion matters: scripts/check-field-types.js only scans the
 * three CORE schema files, so an extension field type that doesn't resolve fails
 * silently at runtime instead of failing CI.
 */
import { render, screen, waitFor } from '@testing-library/react';

const mockAPI = { coverage: vi.fn() };
vi.mock('../../utils/api/posterSelfHeal.js', () => ({ posterSelfHealAPI: mockAPI }));
vi.mock('react-router', () => ({
    Link: ({ children, ...rest }) => <a {...rest}>{children}</a>,
}));

const { PosterSelfHealCoverageField } = await import('./CoverageField.jsx');
const { FieldRegistry } = await import('../../components/fields/FieldRegistry.jsx');
const { POSTER_SELF_HEAL_SCHEMA } = await import('./settings_schema.js');
await import('./manifest.jsx'); // registers the field type as a side effect

const ok = data => ({ data });

describe('field type registration', () => {
    it('registers the exact type the schema asks for', () => {
        const field = POSTER_SELF_HEAL_SCHEMA.fields.find(f => f.key === 'assessed_locations');
        expect(field).toBeTruthy();
        // Identity, not truthiness: getField() returns an UnknownFieldType
        // placeholder for an unregistered type, so a truthy check can never fail
        // and a typo'd `type:` would sail through CI into a blank settings row.
        expect(FieldRegistry.getField(field.type)).toBe(PosterSelfHealCoverageField);
    });
});

describe('PosterSelfHealCoverageField', () => {
    it('lists the folders and Drives being assessed', async () => {
        mockAPI.coverage.mockResolvedValue(
            ok({
                available: true,
                folders: [{ name: 'Logos', path: '/art/logos', types: ['logo'] }],
                drives: [{ name: 'Logos', folder_id: 'LOGOS_ID', heals_types: ['logo'] }],
                unrouted_types: [],
            })
        );
        render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(screen.getByText('/art/logos')).toBeInTheDocument());
        expect(screen.getByText('LOGOS_ID')).toBeInTheDocument();
    });

    it('warns when a type reaches no Drive', async () => {
        mockAPI.coverage.mockResolvedValue(
            ok({
                available: true,
                folders: [{ name: 'Local', path: '/art', types: ['squareart'] }],
                drives: [],
                unrouted_types: ['squareart'],
            })
        );
        render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(screen.getByText(/No Drive receives/)).toBeInTheDocument());
        expect(screen.getByText(/keeps the old names/)).toBeInTheDocument();
    });

    it('shows a folder that claims no types — it is still assessed', async () => {
        mockAPI.coverage.mockResolvedValue(
            ok({
                available: true,
                folders: [{ name: 'Inert', path: '/art/orphans', types: [] }],
                drives: [],
                unrouted_types: [],
            })
        );
        render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(screen.getByText('/art/orphans')).toBeInTheDocument());
        expect(screen.getByText('nothing routed')).toBeInTheDocument();
    });

    it('says so when nothing is configured', async () => {
        mockAPI.coverage.mockResolvedValue(
            ok({ available: true, folders: [], drives: [], unrouted_types: [] })
        );
        render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(screen.getByText(/nothing to assess/)).toBeInTheDocument());
    });

    it('reports a failure instead of rendering an empty strip', async () => {
        mockAPI.coverage.mockRejectedValue(new Error('boom'));
        render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
    });

    it('stays silent when the request is aborted on unmount', async () => {
        const abort = new Error('aborted');
        abort.name = 'AbortError';
        mockAPI.coverage.mockRejectedValue(abort);
        render(<PosterSelfHealCoverageField />);
        // An abort is not a failure to show the user — the loading line stays.
        await waitFor(() => expect(screen.getByText(/Reading save locations/)).toBeInTheDocument());
    });

    it('passes an AbortSignal so unmount can cancel', async () => {
        mockAPI.coverage.mockResolvedValue(
            ok({ available: true, folders: [], drives: [], unrouted_types: [] })
        );
        const { unmount } = render(<PosterSelfHealCoverageField />);
        await waitFor(() => expect(mockAPI.coverage).toHaveBeenCalled());
        // Last call, not first: correct today because restoreMocks clears state
        // between tests, but this stays right if that config ever changes.
        const calls = mockAPI.coverage.mock.calls;
        const passed = calls[calls.length - 1][0];
        expect(passed.signal).toBeInstanceOf(AbortSignal);
        expect(passed.signal.aborted).toBe(false);
        unmount();
        expect(passed.signal.aborted).toBe(true);
    });
});
