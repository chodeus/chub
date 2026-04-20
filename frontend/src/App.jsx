import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ToastProvider } from './contexts/ToastContext.jsx';
import { ThemeProvider } from './contexts/ThemeContext.jsx';
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx';
import { ErrorProvider } from './components/error/ErrorContext.jsx';
import { UIStateProvider } from './contexts/UIStateContext.jsx';
import { SearchCoordinatorProvider } from './contexts/SearchCoordinatorContext.jsx';
import { PageErrorBoundary } from './components/error';
import Layout from './components/Layout.jsx';
import Spinner from './components/ui/Spinner.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import LoginPage from './pages/LoginPage.jsx';

// Lazy-loaded pages - settings
const ModuleSettingsPage = React.lazy(
    () => import('./pages/settings/modules/ModuleSettingsPage.jsx')
);
const GeneralSettingsPage = React.lazy(() => import('./pages/settings/GeneralSettingsPage.jsx'));
const UISettingsPage = React.lazy(() => import('./pages/settings/UISettingsPage.jsx'));
const SchedulePage = React.lazy(() =>
    import('./pages/settings/SchedulePage.jsx').then(m => ({ default: m.SchedulePage }))
);
const InstancesPage = React.lazy(() =>
    import('./pages/settings/InstancesPage.jsx').then(m => ({ default: m.InstancesPage }))
);
const NotificationsPage = React.lazy(() =>
    import('./pages/settings/NotificationsPage.jsx').then(m => ({ default: m.NotificationsPage }))
);
const SettingsSplash = React.lazy(() =>
    import('./pages/SettingsSplash.jsx').then(m => ({ default: m.SettingsSplash }))
);
const JobsPage = React.lazy(() =>
    import('./pages/settings/JobsPage.jsx').then(m => ({ default: m.JobsPage }))
);
const WebhooksPage = React.lazy(() =>
    import('./pages/settings/WebhooksPage.jsx').then(m => ({ default: m.WebhooksPage }))
);

// Lazy-loaded pages - other
const Logs = React.lazy(() => import('./pages/Logs.jsx'));

// Lazy-loaded pages - media
const MediaSearchPage = React.lazy(() => import('./pages/media/MediaSearchPage.jsx'));
const MediaManagePage = React.lazy(() => import('./pages/media/MediaManagePage.jsx'));
const MediaStatsPage = React.lazy(() => import('./pages/media/MediaStatsPage.jsx'));
const LabelarrPage = React.lazy(() => import('./pages/media/LabelarrPage.jsx'));

// Lazy-loaded pages - poster
const PosterGDriveSearchPage = React.lazy(
    () => import('./pages/poster/PosterGDriveSearchPage.jsx')
);
const PosterAssetsSearchPage = React.lazy(
    () => import('./pages/poster/PosterAssetsSearchPage.jsx')
);
const PosterCleanarrPage = React.lazy(() => import('./pages/poster/PosterCleanarrPage.jsx'));
const PosterStatsPage = React.lazy(() => import('./pages/poster/PosterStatsPage.jsx'));

// Lazy-loaded dev pages
const ErrorTestPage = React.lazy(() => import('./pages/dev/ErrorTestPage.jsx'));
const FieldTestPage = React.lazy(() => import('./pages/dev/FieldTestPage.jsx'));
const ApiTestPage = React.lazy(() => import('./pages/dev/ApiTestPage.jsx'));
const ToolbarTestPage = React.lazy(() => import('./pages/dev/ToolbarTestPage.jsx'));
const ToolbarCompoundTest = React.lazy(() => import('./pages/dev/ToolbarCompoundTest.jsx'));
const SpinnerTestPage = React.lazy(() => import('./pages/dev/SpinnerTestPage.jsx'));
const SettingsMockPage = React.lazy(() => import('./pages/dev/SettingsMockPage.jsx'));
const ArrayObjectFieldPage = React.lazy(() => import('./pages/dev/ArrayObjectFieldPage.jsx'));
const AccordionTestPage = React.lazy(() => import('./pages/dev/AccordionTestPage.jsx'));
const StatsPrimitivesTestPage = React.lazy(() => import('./pages/dev/StatsPrimitivesTestPage.jsx'));
const ButtonPrimitivesTestPage = React.lazy(
    () => import('./pages/dev/ButtonPrimitivesTestPage.jsx')
);
const CardPrimitivesTestPage = React.lazy(() => import('./pages/dev/CardPrimitivesTestPage.jsx'));
const FormCompoundsTest = React.lazy(() => import('./pages/dev/FormCompoundsTest.jsx'));
const ModalsTestPage = React.lazy(() => import('./pages/dev/ModalsTestPage.jsx'));
const LogPerformance = React.lazy(() => import('./pages/dev/LogPerformance.jsx'));

const SuspenseFallback = () => <Spinner size="large" text="Loading..." center />;

/**
 * Auth gate — redirects to /login when auth is configured but user is not authenticated.
 * Renders children directly when auth is not yet configured (first-run) or user is logged in.
 */
const RequireAuth = ({ children }) => {
    const { loading, authConfigured, isAuthenticated } = useAuth();
    if (loading) return <SuspenseFallback />;
    if (authConfigured && !isAuthenticated) return <Navigate to="/login" replace />;
    return children;
};

/**
 * Login route gate — redirects authenticated users away from login page.
 */
const LoginRoute = () => {
    const { loading, authConfigured, isAuthenticated } = useAuth();
    if (loading) return <SuspenseFallback />;
    if (isAuthenticated && authConfigured) return <Navigate to="/dashboard" replace />;
    return <LoginPage />;
};

/**
 * CHUB Application Root - Phase 5 Complete
 *
 * Clean provider hierarchy with primitive composition error system:
 * 1. ToastProvider (outermost)
 * 2. ThemeProvider
 * 3. ErrorProvider (new primitive composition system)
 * 4. UIStateProvider
 * 5. Router
 * 6. SearchCoordinatorProvider
 * 7. RouteErrorProvider (innermost)
 *
 * Error boundaries now use atomic primitive composition pattern.
 * All context providers maintained in exact order.
 */

/**
 * Route Error Boundary - Catches route-specific errors with sophisticated recovery
 */
const RouteErrorBoundary = ({ children }) => {
    return (
        <PageErrorBoundary
            pageName="Application"
            pageDescription="Main application routing"
            showNavigation={true}
            showRetry={true}
        >
            {children}
        </PageErrorBoundary>
    );
};

/**
 * Main Application Component - Phase 5 Complete
 * Provider hierarchy with primitive composition error system
 */
const App = () => {
    return (
        // Provider hierarchy:
        // 1. ToastProvider (outermost)
        // 2. ThemeProvider
        // 3. AuthProvider
        // 4. ErrorProvider
        // 5. UIStateProvider
        // 6. Router
        // 7. SearchCoordinatorProvider
        // 8. RouteErrorProvider (innermost)
        <ToastProvider>
            <ThemeProvider>
                <AuthProvider>
                    <ErrorProvider>
                        <UIStateProvider>
                            <BrowserRouter>
                                <SearchCoordinatorProvider>
                                    <RouteErrorBoundary>
                                        <Suspense fallback={<SuspenseFallback />}>
                                            <Routes>
                                                <Route path="/login" element={<LoginRoute />} />
                                                <Route
                                                    path="/"
                                                    element={
                                                        <RequireAuth>
                                                            <Layout />
                                                        </RequireAuth>
                                                    }
                                                >
                                                    <Route
                                                        index
                                                        element={
                                                            <Navigate to="/dashboard" replace />
                                                        }
                                                    />
                                                    <Route
                                                        path="dashboard"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Dashboard"
                                                                pageDescription="Main dashboard overview"
                                                            >
                                                                <DashboardPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />

                                                    {/* Media Section - Hierarchical Routes */}
                                                    <Route
                                                        path="media"
                                                        element={
                                                            <Navigate to="/media/search" replace />
                                                        }
                                                    />
                                                    <Route
                                                        path="media/search"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Media Search"
                                                                pageDescription="Search media collection"
                                                            >
                                                                <MediaSearchPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="media/manage"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Media Management"
                                                                pageDescription="Manage media library"
                                                            >
                                                                <MediaManagePage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="media/statistics"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Media Statistics"
                                                                pageDescription="Media library statistics"
                                                            >
                                                                <MediaStatsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />

                                                    <Route
                                                        path="media/labelarr"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Label Sync"
                                                                pageDescription="Sync labels between services"
                                                            >
                                                                <LabelarrPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />

                                                    {/* Poster Section - Hierarchical Routes (note: /poster not /posters) */}
                                                    <Route
                                                        path="poster"
                                                        element={
                                                            <Navigate
                                                                to="/poster/search/gdrive"
                                                                replace
                                                            />
                                                        }
                                                    />
                                                    <Route
                                                        path="poster/search/gdrive"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="GDrive Poster Search"
                                                                pageDescription="Search GDrive for posters"
                                                            >
                                                                <PosterGDriveSearchPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="poster/search/assets"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Assets Poster Search"
                                                                pageDescription="Search local poster assets"
                                                            >
                                                                <PosterAssetsSearchPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="poster/cleanarr"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Poster Cleanarr"
                                                                pageDescription="Review and clean up unused Plex poster variants"
                                                            >
                                                                <PosterCleanarrPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    {/* Back-compat redirect for any bookmarks still pointing at /poster/manage. */}
                                                    <Route
                                                        path="poster/manage"
                                                        element={
                                                            <Navigate
                                                                to="/poster/cleanarr"
                                                                replace
                                                            />
                                                        }
                                                    />
                                                    <Route
                                                        path="poster/statistics"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Poster Statistics"
                                                                pageDescription="Poster collection statistics"
                                                            >
                                                                <PosterStatsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />

                                                    {/* Settings Section - Direct Routes */}
                                                    <Route
                                                        path="settings"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Settings"
                                                                pageDescription="Settings navigation and configuration hub"
                                                            >
                                                                <SettingsSplash />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/general"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="General Settings"
                                                                pageDescription="General CHUB application settings"
                                                            >
                                                                <GeneralSettingsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/interface"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="User Interface Settings"
                                                                pageDescription="UI theme and appearance settings"
                                                            >
                                                                <UISettingsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/modules"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Module Settings"
                                                                pageDescription="Module-specific configuration settings"
                                                            >
                                                                <ModuleSettingsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/schedule"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Schedule Settings"
                                                                pageDescription="Module scheduling and automation configuration"
                                                            >
                                                                <SchedulePage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/instances"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Instance Management"
                                                                pageDescription="Service instance configuration and connection testing"
                                                            >
                                                                <InstancesPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/notifications"
                                                        element={
                                                            <PageErrorBoundary routeName="Notification Settings">
                                                                <NotificationsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/jobs"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Job Queue"
                                                                pageDescription="Background job management"
                                                            >
                                                                <JobsPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="settings/webhooks"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Webhooks"
                                                                pageDescription="Webhook processors and cleanup operations"
                                                            >
                                                                <WebhooksPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    {/* Logs Route */}
                                                    <Route
                                                        path="logs"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="System Logs"
                                                                pageDescription="Real-time log viewer with search and download"
                                                            >
                                                                <Logs />
                                                            </PageErrorBoundary>
                                                        }
                                                    />

                                                    {/* Development Routes */}
                                                    <Route
                                                        path="dev/error"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Error Test"
                                                                pageDescription="Error handling demonstration page"
                                                            >
                                                                <ErrorTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/fields"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Field Test"
                                                                pageDescription="Field system development testing interface"
                                                            >
                                                                <FieldTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/api"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="API Test"
                                                                pageDescription="API Testing"
                                                            >
                                                                <ApiTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/toolbar"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Toolbar Test"
                                                                pageDescription="Toolbar overflow testing"
                                                            >
                                                                <ToolbarTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/toolbar"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Toolbar Compound Pattern Test"
                                                                pageDescription="Toolbar compound component pattern testing"
                                                            >
                                                                <ToolbarCompoundTest />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/spinner"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Spinner Test"
                                                                pageDescription="Spinner component testing and development"
                                                            >
                                                                <SpinnerTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/settings"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Settings Mock"
                                                                pageDescription="Settings accordion interface mockup and design exploration"
                                                            >
                                                                <SettingsMockPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/array-object-field"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Array Object Field"
                                                                pageDescription="Unified ArrayObjectField component demonstration"
                                                            >
                                                                <ArrayObjectFieldPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/accordion"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Accordion Test"
                                                                pageDescription="AccordionItem compound component validation and testing"
                                                            >
                                                                <AccordionTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/stats"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Statistics Primitives Test"
                                                                pageDescription="Statistics System primitive composition and layout testing"
                                                            >
                                                                <StatsPrimitivesTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/buttons"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Button Primitives Test"
                                                                pageDescription="Button System primitive composition and component testing"
                                                            >
                                                                <ButtonPrimitivesTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/card"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Card Primitives Test"
                                                                pageDescription="Card System primitive composition and variant testing"
                                                            >
                                                                <CardPrimitivesTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/form-compounds"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Form Compounds Test"
                                                                pageDescription="Form System compound composition validation (Header, Section, Actions)"
                                                            >
                                                                <FormCompoundsTest />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/modals"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Modal Test"
                                                                pageDescription="Modal System comprehensive testing and real-world examples"
                                                            >
                                                                <ModalsTestPage />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                    <Route
                                                        path="dev/log-performance"
                                                        element={
                                                            <PageErrorBoundary
                                                                pageName="Log Performance Test"
                                                                pageDescription="Phase 2 Log Output component performance validation"
                                                            >
                                                                <LogPerformance />
                                                            </PageErrorBoundary>
                                                        }
                                                    />
                                                </Route>
                                                <Route
                                                    path="*"
                                                    element={<Navigate to="/dashboard" replace />}
                                                />
                                            </Routes>
                                        </Suspense>
                                    </RouteErrorBoundary>
                                </SearchCoordinatorProvider>
                            </BrowserRouter>
                        </UIStateProvider>
                    </ErrorProvider>
                </AuthProvider>
            </ThemeProvider>
        </ToastProvider>
    );
};

export default App;
