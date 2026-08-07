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
 *  rating_key null and title "" (plex_metadata.py) — the exact shape that used
 *  to collapse both rows onto one identity. */
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
});

describe('Poster Cleanarr — unanchored bundle identity', () => {
    it('lists both null-rating_key bundles as separate rows', () => {
        scanPayload = payload([GHOST_A, GHOST_B]);
        render(<PosterCleanarrPage />);
        // Both render as "(unknown)" — title is "" for unanchored bundles.
        expect(screen.getAllByText('(unknown)')).toHaveLength(2);
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

        // rating_key null = nothing in Plex to promote against; the endpoint
        // 400s, so the control must not be offered.
        expect(screen.getByRole('button', { name: /Make active & delete rest/i })).toBeDisabled();
    });
});

describe('Poster Cleanarr — persisted tree state', () => {
    it('ignores a stale v2 selection instead of stranding the page', () => {
        // v2 stored { kind, ratingKey }; the tree is keyed by bundle_path now.
        localStorage.setItem(
            'chub_cleanarr_state_v2',
            JSON.stringify({ tab: 'all', selected: { kind: 'show', ratingKey: 123 } })
        );
        scanPayload = payload([GHOST_A]);
        render(<PosterCleanarrPage />);

        // The v3 key means the old blob is never read, so nothing is selected
        // and the left pane still lists the bundle.
        expect(screen.getAllByText('(unknown)')).toHaveLength(1);
        expect(screen.getByText(/Select an item on the left/i)).toBeInTheDocument();
    });
});
