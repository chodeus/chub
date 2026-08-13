import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';

const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

// Mirrors every postersAPI method the page touches — a missing one surfaces as
// "x is not a function" from deep inside a render.
const mockPostersAPI = {
    listPlexMetadataByMedia: vi.fn(),
    enqueuePlexMetadataScan: vi.fn(),
    deletePlexMetadataVariant: vi.fn(),
    setPlexMetadataActive: vi.fn(),
    runPlexMetadataCleanup: vi.fn(),
    getPlexVariantUrl: vi.fn(() => ''),
    scanKometaAssets: vi.fn(),
    enqueueKometaAssetsScan: vi.fn(),
};
vi.mock('../../utils/api/posters.js', () => ({ postersAPI: mockPostersAPI }));
vi.mock('../../hooks/useStreamToken.js', () => ({ useStreamToken: () => null }));
vi.mock('react-router', () => ({
    Link: ({ children, ...rest }) => <a {...rest}>{children}</a>,
}));
const toast = { success: vi.fn(), error: vi.fn() };
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

let scanPayload = null;
const refresh = vi.fn();
vi.mock('../../hooks/useApiData.js', () => ({
    useApiData: () => ({ data: { data: scanPayload }, isLoading: false, error: null, refresh }),
}));

const PosterCleanarrPage = (await import('./PosterCleanarrPage.jsx')).default;

const variant = (path, filename, active = false) => ({
    path,
    filename,
    size: 1024,
    mtime: 0,
    kind: 'poster',
    source: 'uploads',
    active,
});

/** Two unanchored orphan bundles. The backend deliberately keeps these with
 *  rating_key null and title "" (plex_metadata.py) — the shape that used to
 *  collapse onto one identity in the tree Map and the detail lookup. Note the
 *  left-pane LIST was always keyed by bundle_path, so row count never regressed;
 *  the selection and stale-attribution tests are what cover that bug. */
const GHOST_A = {
    bundle_path: '/plex/Metadata/Movies/a/ghost_a.bundle',
    rating_key: null,
    title: '',
    year: null,
    metadata_type: null,
    metadata_type_label: null,
    library_section_id: null,
    library_name: null,
    variants: [variant('/plex/.../ghost_a/only_a', 'only_a')],
};
const GHOST_B = {
    bundle_path: '/plex/Metadata/Movies/b/ghost_b.bundle',
    rating_key: null,
    title: '',
    year: null,
    metadata_type: null,
    metadata_type_label: null,
    library_section_id: null,
    library_name: null,
    variants: [variant('/plex/.../ghost_b/only_b', 'only_b')],
};

const payload = bundles => ({
    bundles,
    stats: {
        bundle_count: bundles.length,
        variant_count: bundles.reduce((n, b) => n + b.variants.length, 0),
        bloat_count: 1,
        bloat_size: 1024,
        scanned_at: 0,
    },
    transcoder: null,
});

beforeEach(() => {
    scanPayload = null;
    localStorage.clear();
    // Must be set here, not at the mock literal: `mockReset` wipes a
    // module-scope mockResolvedValue before every test. A bare vi.fn() returns
    // undefined, which leaves staleItems empty and the stale-attribution memo
    // permanently short-circuited at its `if (!staleItems.length)` early exit.
    mockPostersAPI.scanKometaAssets.mockResolvedValue({ data: { stale: [], orphans: [] } });
});

describe('Poster Cleanarr — unanchored bundle identity', () => {
    it('lists both null-rating_key bundles as separate rows', async () => {
        scanPayload = payload([GHOST_A, GHOST_B]);
        render(<PosterCleanarrPage />);
        // findAll, not getAll: the mount effect resolves asynchronously, and a
        // synchronous assertion races it into an act() warning.
        // Both render as "(unknown)" — title is "" for unanchored bundles.
        expect(await screen.findAllByText('(unknown)')).toHaveLength(2);
    });

    it('selecting one shows only that bundle’s variants, not the other’s', async () => {
        const user = userEvent.setup();
        scanPayload = payload([GHOST_A, GHOST_B]);
        render(<PosterCleanarrPage />);

        // Keyed by rating_key, the tree Map (last writer wins) and the detail
        // lookup (first match wins) resolved to DIFFERENT bundles, so clicking
        // the first row showed the second's files — and deleting removed them.
        // Variant tiles carry the filename as the image's alt text.
        await user.click(screen.getAllByText('(unknown)')[0]);
        expect(await screen.findByAltText('only_a')).toBeInTheDocument();
        expect(screen.queryByAltText('only_b')).not.toBeInTheDocument();

        await user.click(screen.getAllByText('(unknown)')[1]);
        expect(await screen.findByAltText('only_b')).toBeInTheDocument();
        expect(screen.queryByAltText('only_a')).not.toBeInTheDocument();
    });

    it('disables "Make active & delete rest" when the bundle has no Plex item', async () => {
        const user = userEvent.setup();
        scanPayload = payload([GHOST_A]);
        render(<PosterCleanarrPage />);

        await user.click(screen.getAllByText('(unknown)')[0]);
        await screen.findByAltText('only_a');
        // Ticking one variant is load-bearing: `disabled` is
        // `selectedPaths.size !== 1 || !detail.bundle.rating_key`, so without a
        // selection the size clause alone passes and the guard goes untested.
        await user.click(screen.getByRole('button', { name: 'Select variant' }));

        // rating_key null = nothing in Plex to promote against; the endpoint
        // 400s, so the control must not be offered.
        expect(screen.getByRole('button', { name: /Make active & delete rest/i })).toBeDisabled();
    });

    it('enables it once the bundle is anchored in Plex', async () => {
        const user = userEvent.setup();
        // The positive control — without it a blanket `disabled` would pass above.
        scanPayload = payload([{ ...GHOST_A, rating_key: 4242, title: 'Real Movie' }]);
        render(<PosterCleanarrPage />);

        await user.click(screen.getByText('Real Movie'));
        await screen.findByAltText('only_a');
        await user.click(screen.getByRole('button', { name: 'Select variant' }));

        expect(screen.getByRole('button', { name: /Make active & delete rest/i })).toBeEnabled();
    });
});

describe('Poster Cleanarr — stale folder attribution', () => {
    it('attributes a stale folder to the bundle it belongs to, keyed by bundle_path', async () => {
        const ANCHORED = {
            ...GHOST_A,
            bundle_path: '/plex/Metadata/Movies/r/real.bundle',
            rating_key: 4242,
            title: 'Real Movie',
            year: 2019,
            variants: [variant('/plex/.../real/only_real', 'only_real')],
        };
        // The counts map is read as staleByBundle.get(bundle.bundle_path); keying
        // it by rating_key again makes every badge read 0.
        mockPostersAPI.scanKometaAssets.mockResolvedValue({
            data: {
                stale: [
                    {
                        rating_key: 4242,
                        plex_title: 'Real Movie',
                        plex_year: 2019,
                        name: 'Real Movie (2019) [tmdb-1]',
                        canonical: 'Real Movie (2019)',
                        canonical_present: true,
                        size: 10,
                        folder: '/assets/Real Movie (2019) [tmdb-1]',
                    },
                ],
                orphans: [],
            },
        });
        scanPayload = payload([ANCHORED, GHOST_A]);
        render(<PosterCleanarrPage />);

        // The pill renders "⧉ 1" only on the row that owns the stale folder.
        expect(await screen.findByTitle('Stale duplicate asset folder')).toHaveTextContent('1');
    });

    it('does not attribute an unmatchable stale folder to an arbitrary unanchored bundle', async () => {
        // Both ghosts share rating_key null and title "" — indexing them would
        // let this land on whichever was seen last.
        mockPostersAPI.scanKometaAssets.mockResolvedValue({
            data: {
                stale: [
                    {
                        rating_key: null,
                        plex_title: '',
                        plex_year: null,
                        name: 'Nowhere (1999)',
                        canonical: 'Nowhere (1999)',
                        canonical_present: false,
                        size: 10,
                        folder: '/assets/Nowhere (1999)',
                    },
                ],
                orphans: [],
            },
        });
        scanPayload = payload([GHOST_A, GHOST_B]);
        render(<PosterCleanarrPage />);

        await screen.findAllByText('(unknown)');
        expect(screen.queryByTitle('Stale duplicate asset folder')).not.toBeInTheDocument();
    });
});

describe('Poster Cleanarr — persisted tree state', () => {
    it('ignores a stale v2 selection instead of stranding the page', async () => {
        // v2 stored { kind, ratingKey }; the tree is keyed by bundle_path now.
        localStorage.setItem(
            'chub_cleanarr_state_v2',
            JSON.stringify({ tab: 'all', selected: { kind: 'show', ratingKey: 123 } })
        );
        scanPayload = payload([GHOST_A]);
        render(<PosterCleanarrPage />);

        // The v3 key means the old blob is never read, so nothing is selected
        // and the left pane still lists the bundle.
        expect(await screen.findAllByText('(unknown)')).toHaveLength(1);
        expect(screen.getByText(/Select an item on the left/i)).toBeInTheDocument();
    });

    it('does not strand the mobile layout when a v2 selection is present', async () => {
        // Desktop can't see this: the left pane renders regardless. On mobile a
        // truthy `selected` HIDES the list, and "Back to list" lives inside the
        // detail pane — which never renders when the selection resolves to no
        // bundle. Reverting STATE_KEY to v2 leaves the page with no way out.
        const realMatchMedia = window.matchMedia;
        window.matchMedia = query => ({
            ...realMatchMedia(query),
            matches: query.includes('max-width: 767px'),
        });
        try {
            localStorage.setItem(
                'chub_cleanarr_state_v2',
                JSON.stringify({ tab: 'all', selected: { kind: 'show', ratingKey: 123 } })
            );
            scanPayload = payload([GHOST_A]);
            render(<PosterCleanarrPage />);

            // The bundle list must still be reachable.
            expect(await screen.findAllByText('(unknown)')).toHaveLength(1);
        } finally {
            window.matchMedia = realMatchMedia;
        }
    });
});
