/** A source folder's picker checks CHUB can write there only while File Action is "move". */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { UIStateProvider } from '../../../contexts/UIStateContext.jsx';

const api = vi.hoisted(() => ({ probes: [], config: {} }));

vi.mock('../../../utils/api/system.js', () => ({
    systemAPI: {
        listAllowedRoots: () => Promise.resolve({ data: { roots: ['/posters'] } }),
        listDirectory: (path, options = {}) => {
            api.probes.push([path, !!options.checkWrite]);
            return Promise.resolve({ data: { directories: [] } });
        },
        createDirectory: () => Promise.resolve(),
    },
}));
vi.mock('../../../utils/api/config.js', () => ({
    configAPI: {
        fetchConfig: () => Promise.resolve({ data: api.config }),
        fetchSection: () => Promise.resolve({ data: {} }),
        fetchGdriveCredentialStatus: () => Promise.resolve({ data: {} }),
        updateConfig: vi.fn(),
    },
}));
vi.mock('../../../utils/api/modules.js', () => ({
    modulesAPI: {
        getModuleSchema: () => Promise.reject(new Error('offline')),
        runModule: vi.fn(),
    },
}));
vi.mock('../../../contexts/ToastContext.jsx', () => ({
    useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }),
}));

const { ModuleSettingsPage } = await import('./ModuleSettingsPage.jsx');

const openPage = async (moduleKey, settings) => {
    api.config = { [moduleKey]: { apply_method: 'kometa', source_dirs: [], ...settings } };
    render(
        <UIStateProvider>
            <MemoryRouter initialEntries={[`/settings/modules/${moduleKey}`]}>
                <Routes>
                    <Route path="/settings/modules/:moduleKey" element={<ModuleSettingsPage />} />
                </Routes>
            </MemoryRouter>
        </UIStateProvider>
    );
    return screen.findAllByLabelText(/^File Action/);
};

const browseSourceFolder = async () => {
    api.probes.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Browse for Source Directories 1' }));
    await waitFor(() => expect(api.probes.length).toBeGreaterThan(0));
    return api.probes[0][1];
};

describe.each(['poster_renamerr', 'asset_renamerr'])('%s source folders', moduleKey => {
    it('are write-checked once File Action is switched to move, and not after it is switched back', async () => {
        const [fileAction] = await openPage(moduleKey, { action_type: 'copy' });
        expect(await browseSourceFolder()).toBe(false);
        fireEvent.keyDown(document.activeElement, { key: 'Escape' });

        fireEvent.change(fileAction, { target: { value: 'move' } });
        expect(await browseSourceFolder()).toBe(true);
        fireEvent.keyDown(document.activeElement, { key: 'Escape' });

        fireEvent.change(fileAction, { target: { value: 'copy' } });
        expect(await browseSourceFolder()).toBe(false);
    });
});
