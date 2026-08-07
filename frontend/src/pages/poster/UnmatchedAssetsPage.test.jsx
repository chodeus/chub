import { render as rtlRender, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UIStateProvider } from '../../contexts/UIStateContext.jsx';

// Modal reads useUIState, so every render needs the provider.
const render = ui => rtlRender(ui, { wrapper: UIStateProvider });

// Every mock is hoisted above the import of the page under test.
const mockPostersAPI = {
    fetchUnmatchedDetails: vi.fn(),
    fetchUnmatchedArtwork: vi.fn(),
    fetchRecentlyMatched: vi.fn(),
    setMatchIgnored: vi.fn(),
    fetchMatchCandidates: vi.fn(),
    applyMatch: vi.fn(),
    getThumbnailUrl: vi.fn(() => ''),
};

vi.mock('../../utils/api/posters.js', () => ({ postersAPI: mockPostersAPI }));
vi.mock('../../utils/api/system.js', () => ({ systemAPI: { resetPosterMatches: vi.fn() } }));
vi.mock('../../hooks/useStreamToken.js', () => ({ useStreamToken: () => null }));
vi.mock('../../extensions/index.js', () => ({ extensionCapability: () => null }));
vi.mock('react-router', () => ({
    Link: ({ children, ...rest }) => <a {...rest}>{children}</a>,
}));

const toast = { success: vi.fn(), error: vi.fn() };
vi.mock('../../contexts/ToastContext.jsx', () => ({ useToast: () => toast }));

// The page calls useApiData three times; only the first (unmatched details)
// carries the fixture. Keyed on apiFunction so order changes don't break this.
let unmatchedPayload = null;
const refresh = vi.fn();
vi.mock('../../hooks/useApiData.js', () => ({
    useApiData: ({ apiFunction }) => ({
        data:
            apiFunction === mockPostersAPI.fetchUnmatchedDetails
                ? { data: unmatchedPayload }
                : null,
        isLoading: false,
        error: null,
        refresh,
    }),
}));

const UnmatchedAssetsPage = (await import('./UnmatchedAssetsPage.jsx')).default;

/** The shape backend group_assets() + calculate_stats() actually emit: movies and
 *  collections keep the whole media_cache row, series are aggregates carrying one
 *  target per row. The summary totals are load-bearing — the page hides the whole
 *  view behind `hasData`, which needs a non-zero total. */
const payload = ({ movies = [], series = [], collections = [] } = {}) => ({
    unmatched: { movies, series, collections },
    summary: {
        movies: { total: movies.length, unmatched: movies.length, percent_complete: 0 },
        series: { total: series.length, unmatched: series.length, percent_complete: 0 },
        seasons: { total: 0, unmatched: 0, percent_complete: 0 },
        collections: {
            total: collections.length,
            unmatched: collections.length,
            percent_complete: 0,
        },
    },
    needs_review: [],
    ignored: [],
    locked: [],
});

const A_MOVIE = {
    id: 1,
    title: 'Blade Runner 2049',
    year: 2017,
    asset_type: 'movie',
    instance_name: 'radarr',
    tmdb_id: 335984,
};

/** Foundation: missing its show poster plus S01 and S02 — three media_cache rows. */
const A_SERIES = {
    title: 'Foundation',
    year: 2021,
    instance_name: 'sonarr',
    asset_type: 'series',
    tvdb_id: 370377,
    missing_main_poster: true,
    missing_seasons: [1, 2],
    targets: [
        { id: 20, season_number: null },
        { id: 21, season_number: 1 },
        { id: 22, season_number: 2 },
    ],
};

// Matches only the row Ignore control — /^Ignore/ alone also catches the
// "Ignored" view tab.
const IGNORE_BTN = /^Ignore (this item|— choose what to hide)$/;
const ignoreButtonsIn = () => screen.queryAllByRole('button', { name: IGNORE_BTN });

/** Every setMatchIgnored call as [id, payload], id-ordered — asserting on whole
 *  calls catches a wrong `ignored` value that an id-only check would miss. */
const sortedIgnoreCalls = () =>
    [...mockPostersAPI.setMatchIgnored.mock.calls].sort((a, b) => a[0] - b[0]);

beforeEach(() => {
    unmatchedPayload = null;
    mockPostersAPI.setMatchIgnored.mockResolvedValue({});
    mockPostersAPI.fetchMatchCandidates.mockResolvedValue({ data: { candidates: [] } });
});

describe('Unmatched tab — row actions', () => {
    it('renders Ignore on a series row (the reported bug: it only rendered on movies)', () => {
        unmatchedPayload = payload({ movies: [A_MOVIE], series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        expect(screen.getByText('Blade Runner 2049')).toBeInTheDocument();
        expect(screen.getByText('Foundation')).toBeInTheDocument();
        // One per row. Before the fix the series row rendered none, because the
        // backend dropped its media_cache id and the gate was `item.id != null`.
        expect(ignoreButtonsIn()).toHaveLength(2);
    });

    it('renders neither Ignore nor Match for a row the backend gave no targets', () => {
        unmatchedPayload = payload({ series: [{ ...A_SERIES, targets: [] }] });
        render(<UnmatchedAssetsPage />);

        // Positive control first — without it a typo'd query or a row that
        // failed to render would satisfy the absence assertions vacuously.
        expect(screen.getByText('Foundation')).toBeInTheDocument();
        expect(ignoreButtonsIn()).toHaveLength(0);
        // Match shares the gate. Rendering it without an id is the original
        // bug's other half: it requested /posters/match/undefined/candidates
        // and the swallowed 422 read as "nothing in your cache".
        expect(screen.queryByRole('button', { name: 'Match' })).not.toBeInTheDocument();
    });

    it('renders Match on a row that does have targets', () => {
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);
        expect(screen.getByRole('button', { name: 'Match' })).toBeInTheDocument();
    });

    it('ignores a single-target row straight from the button, with no picker', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({ movies: [A_MOVIE] });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);

        expect(mockPostersAPI.setMatchIgnored).toHaveBeenCalledTimes(1);
        expect(mockPostersAPI.setMatchIgnored).toHaveBeenCalledWith(1, {
            kind: 'media',
            ignored: true,
        });
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('sends kind=collection for a collection row', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({
            collections: [{ id: 9, title: 'John Wick Collection', asset_type: 'collection' }],
        });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);

        expect(mockPostersAPI.setMatchIgnored).toHaveBeenCalledWith(9, {
            kind: 'collection',
            ignored: true,
        });
    });
});

describe('Unmatched tab — per-target ignore', () => {
    it('opens a picker listing every target on a multi-target row', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);

        const dialog = screen.getByRole('dialog');
        expect(
            within(dialog).getByRole('button', { name: /Everything \(3\)/ })
        ).toBeInTheDocument();
        expect(within(dialog).getByRole('button', { name: /Show poster/ })).toBeInTheDocument();
        expect(within(dialog).getByRole('button', { name: /S01/ })).toBeInTheDocument();
        expect(within(dialog).getByRole('button', { name: /S02/ })).toBeInTheDocument();
        // Opening the picker must not have ignored anything yet.
        expect(mockPostersAPI.setMatchIgnored).not.toHaveBeenCalled();
    });

    it('ignores only the chosen season, not the whole show', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);
        await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /S02/ }));

        expect(mockPostersAPI.setMatchIgnored).toHaveBeenCalledTimes(1);
        expect(mockPostersAPI.setMatchIgnored).toHaveBeenCalledWith(22, {
            kind: 'media',
            ignored: true,
        });
    });

    it('fans "Everything" out over every target — one call per media_cache row', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);
        await user.click(
            within(screen.getByRole('dialog')).getByRole('button', { name: /Everything/ })
        );

        expect(sortedIgnoreCalls()).toEqual([
            [20, { kind: 'media', ignored: true }],
            [21, { kind: 'media', ignored: true }],
            [22, { kind: 'media', ignored: true }],
        ]);
    });

    it('still refreshes when one call in the fan-out fails', async () => {
        const user = userEvent.setup();
        // Partial success already mutated the server; the table must not keep
        // rendering rows that are now ignored.
        mockPostersAPI.setMatchIgnored
            .mockResolvedValueOnce({})
            .mockRejectedValueOnce(new Error('boom'))
            .mockResolvedValueOnce({});
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        await user.click(ignoreButtonsIn()[0]);
        await user.click(
            within(screen.getByRole('dialog')).getByRole('button', { name: /Everything/ })
        );

        expect(refresh).toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('2 of 3'));
    });
});

describe('Ignored tab — grouped rows', () => {
    /** What the backend now sends: one entry per show, carrying a target per
     *  media_cache row it covers. */
    const IGNORED_SERIES = {
        id: 20,
        title: 'Foundation',
        year: 2021,
        type: 'series',
        asset_type: 'series',
        instance_name: 'sonarr',
        missing_main_poster: true,
        missing_seasons: [1, 2],
        targets: [
            { id: 20, season_number: null },
            { id: 21, season_number: 1 },
            { id: 22, season_number: 2 },
        ],
    };

    const openIgnoredTab = async user => {
        await user.click(screen.getByRole('button', { name: /^Ignored/ }));
    };

    it('shows one row with a chip per ignored season', async () => {
        const user = userEvent.setup();
        unmatchedPayload = { ...payload({}), ignored: [IGNORED_SERIES] };
        render(<UnmatchedAssetsPage />);
        await openIgnoredTab(user);

        expect(screen.getAllByText('Foundation')).toHaveLength(1);
        // Without these the grouped row is indistinguishable from any other.
        expect(screen.getByText('Poster')).toBeInTheDocument();
        expect(screen.getByText('S01')).toBeInTheDocument();
        expect(screen.getByText('S02')).toBeInTheDocument();
    });

    it('chips a single-season group too, so it cannot read as the whole show', async () => {
        const user = userEvent.setup();
        // Ignoring only S01 leaves one target. Without a chip this row is
        // indistinguishable from having ignored the entire show.
        unmatchedPayload = {
            ...payload({}),
            ignored: [
                {
                    ...IGNORED_SERIES,
                    id: 21,
                    missing_main_poster: false,
                    missing_seasons: [1],
                    targets: [{ id: 21, season_number: 1 }],
                },
            ],
        };
        render(<UnmatchedAssetsPage />);
        await openIgnoredTab(user);

        expect(screen.getByText('Foundation')).toBeInTheDocument();
        expect(screen.getByText('S01')).toBeInTheDocument();
        expect(screen.queryByText('Poster')).not.toBeInTheDocument();
    });

    it('does not chip a movie row, which is not a group', async () => {
        const user = userEvent.setup();
        unmatchedPayload = {
            ...payload({}),
            ignored: [{ id: 5, title: 'Blade Runner 2049', year: 2017, type: 'movie' }],
        };
        render(<UnmatchedAssetsPage />);
        await openIgnoredTab(user);

        expect(screen.getByText('Blade Runner 2049')).toBeInTheDocument();
        // MissingPosterChips falls back to a bare "Poster" chip for non-series;
        // movies carry no targets so they must not reach it at all.
        expect(screen.queryByText('Poster')).not.toBeInTheDocument();
    });

    it('restores every row the group covers, not just the first', async () => {
        const user = userEvent.setup();
        unmatchedPayload = { ...payload({}), ignored: [IGNORED_SERIES] };
        render(<UnmatchedAssetsPage />);
        await openIgnoredTab(user);

        await user.click(screen.getByRole('button', { name: 'Restore' }));

        // Whole calls, not just the ids: asserting the payload for one target
        // would let a wrong `ignored` value on the other two slip through.
        expect(sortedIgnoreCalls()).toEqual([
            [20, { kind: 'media', ignored: false }],
            [21, { kind: 'media', ignored: false }],
            [22, { kind: 'media', ignored: false }],
        ]);
    });
});

describe('Unmatched tab — poster picker targets', () => {
    it('fetches candidates for the selected season, not just the show row', async () => {
        const user = userEvent.setup();
        unmatchedPayload = payload({ series: [A_SERIES] });
        render(<UnmatchedAssetsPage />);

        await user.click(screen.getAllByRole('button', { name: 'Match' })[0]);

        // Opens on the show's own row (season_number null sorts first).
        expect(mockPostersAPI.fetchMatchCandidates).toHaveBeenLastCalledWith(20, { kind: 'media' });

        const dialog = screen.getByRole('dialog');
        await user.click(within(dialog).getByRole('button', { name: 'S02' }));

        // Candidates are season-filtered server-side, so each target needs its
        // own fetch or that season can never be matched.
        expect(mockPostersAPI.fetchMatchCandidates).toHaveBeenLastCalledWith(22, { kind: 'media' });
    });

    it('reports a failed candidate request as a failure, not an empty cache', async () => {
        const user = userEvent.setup();
        mockPostersAPI.fetchMatchCandidates.mockRejectedValue(new Error('502'));
        unmatchedPayload = payload({ movies: [A_MOVIE] });
        render(<UnmatchedAssetsPage />);

        await user.click(screen.getAllByRole('button', { name: 'Match' })[0]);

        expect(await screen.findByText(/the request failed/i)).toBeInTheDocument();
        expect(
            screen.queryByText(/No candidate posters found in your cache/i)
        ).not.toBeInTheDocument();
    });
});
