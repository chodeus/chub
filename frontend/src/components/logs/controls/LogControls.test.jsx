import { createRef } from 'react';
import { render, screen } from '@testing-library/react';

const mockUIState = { viewport: { width: 1400 } };
vi.mock('../../../contexts/UIStateContext', () => ({ useUIState: () => mockUIState }));

const { LogControls } = await import('./LogControls.jsx');

const renderControls = (props = {}) =>
    render(
        <LogControls
            modules={['cleanarr']}
            logFiles={['cleanarr.log']}
            selectedModule="cleanarr"
            selectedLogFile="cleanarr.log"
            logText="a line"
            onModuleChange={vi.fn()}
            onLogFileChange={vi.fn()}
            onSearchChange={vi.fn()}
            onDownload={vi.fn()}
            {...props}
        />
    );

describe('LogControls', () => {
    afterEach(() => {
        window.innerWidth = 1024;
        mockUIState.viewport = { width: 1400 };
    });

    it('keeps the controls on screen when the window grew past the stacked breakpoint', () => {
        // Mounted phone-width, so the panel starts collapsed; then the window widened.
        window.innerWidth = 500;
        mockUIState.viewport = { width: 1400 };

        renderControls();

        // The collapse toggle only exists in stacked layout, so a hidden panel
        // here would leave no way to bring the controls back.
        expect(screen.queryByRole('button', { name: /Show Controls/ })).toBeNull();
        expect(screen.getByLabelText('Select module')).toBeInTheDocument();
    });

    it('still hides the controls when stacked and collapsed', () => {
        window.innerWidth = 500;
        mockUIState.viewport = { width: 900 };

        renderControls();

        expect(screen.queryByLabelText('Select module')).toBeNull();
        expect(screen.getByRole('button', { name: /Show Controls/ })).toBeInTheDocument();
    });

    it('hands the search field back through the ref so ⌘F can focus it', () => {
        const searchInputRef = createRef();

        renderControls({ searchInputRef });

        expect(searchInputRef.current).toBe(screen.getByLabelText('Search logs'));
    });
});
