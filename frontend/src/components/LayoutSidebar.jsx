import React, { useCallback, useEffect, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useUIState } from '../contexts/UIStateContext.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';

const NAV_SECTIONS = [
    {
        id: 'home',
        heading: null,
        items: [
            {
                id: 'dashboard',
                label: 'Dashboard',
                path: '/dashboard',
                icon: 'home',
                type: 'single',
            },
        ],
    },
    {
        id: 'media',
        heading: 'Media',
        items: [
            {
                id: 'media',
                label: 'Library',
                path: '/media',
                icon: 'movie',
                type: 'parent',
                children: [
                    { id: 'media-search', label: 'Search', path: '/media/search' },
                    { id: 'media-manage', label: 'Manage', path: '/media/manage' },
                    { id: 'media-statistics', label: 'Statistics', path: '/media/statistics' },
                    { id: 'media-labelarr', label: 'Label Sync', path: '/media/labelarr' },
                ],
            },
        ],
    },
    {
        id: 'posters',
        heading: 'Posters',
        items: [
            {
                id: 'poster',
                label: 'Assets',
                path: '/poster',
                icon: 'image',
                type: 'parent',
                children: [
                    { id: 'gdrive-search', label: 'GDrive Search', path: '/poster/search/gdrive' },
                    { id: 'assets-search', label: 'Assets Search', path: '/poster/search/assets' },
                    { id: 'poster-manage', label: 'Poster Cleanarr', path: '/poster/manage' },
                    { id: 'poster-statistics', label: 'Statistics', path: '/poster/statistics' },
                ],
            },
        ],
    },
    {
        id: 'system',
        heading: 'System',
        items: [
            {
                id: 'settings',
                label: 'Settings',
                path: '/settings',
                icon: 'settings',
                type: 'parent',
                children: [
                    { id: 'settings-general', label: 'General', path: '/settings/general' },
                    { id: 'settings-interface', label: 'Interface', path: '/settings/interface' },
                    { id: 'settings-modules', label: 'Modules', path: '/settings/modules' },
                    { id: 'settings-instances', label: 'Instances', path: '/settings/instances' },
                    { id: 'settings-schedule', label: 'Schedule', path: '/settings/schedule' },
                    { id: 'settings-jobs', label: 'Jobs', path: '/settings/jobs' },
                    {
                        id: 'settings-notifications',
                        label: 'Notifications',
                        path: '/settings/notifications',
                    },
                    { id: 'settings-webhooks', label: 'Webhooks', path: '/settings/webhooks' },
                ],
            },
            {
                id: 'logs',
                label: 'Logs',
                path: '/logs',
                icon: 'description',
                type: 'single',
            },
        ],
    },
];

const LayoutSidebar = React.memo(() => {
    const location = useLocation();
    const { mobileMenuOpen, closeMobileMenu, isMobile } = useUIState();
    const { user, logout } = useAuth();
    const sidebarRef = useRef(null);

    const handleParentNavLinkClick = useCallback(() => {}, []);

    const handleChildNavLinkClick = useCallback(() => {
        if (isMobile && mobileMenuOpen) {
            closeMobileMenu();
        }
    }, [isMobile, mobileMenuOpen, closeMobileMenu]);

    useEffect(() => {
        const handleClickOutside = event => {
            if (
                isMobile &&
                mobileMenuOpen &&
                sidebarRef.current &&
                !sidebarRef.current.contains(event.target)
            ) {
                const hamburgerButton = event.target.closest('.hamburger');
                if (!hamburgerButton) {
                    closeMobileMenu();
                }
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isMobile, mobileMenuOpen, closeMobileMenu]);

    const isParentActive = useCallback(
        item => {
            if (item.type !== 'parent') return false;
            return location.pathname.startsWith(item.path + '/') || location.pathname === item.path;
        },
        [location.pathname]
    );

    const isChildActive = useCallback(
        childPath => location.pathname === childPath,
        [location.pathname]
    );

    const isSingleActive = useCallback(path => location.pathname === path, [location.pathname]);

    const userInitial = user ? user.charAt(0).toUpperCase() : '?';

    return (
        <aside
            ref={sidebarRef}
            className={`bg-sidebar-bg overflow-y-auto transition-transform
                ${
                    isMobile
                        ? `fixed inset-y-0 left-0 min-w-sidebar z-50 ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'}`
                        : 'flex-none min-w-sidebar translate-x-0'
                } ${isMobile && mobileMenuOpen ? 'page-sidebar--mobile-open' : ''}`}
            role="navigation"
            aria-label="Main navigation"
            aria-hidden={isMobile && !mobileMenuOpen}
        >
            <div className="flex flex-col h-full py-4">
                {/* Hierarchical Navigation */}
                <nav className="flex-1 px-2">
                    {NAV_SECTIONS.map(section => (
                        <div key={section.id} className="mb-2">
                            {section.heading && (
                                <div className="px-3 pt-4 pb-2 text-xs font-semibold uppercase tracking-wider text-sidebar-secondary opacity-70">
                                    {section.heading}
                                </div>
                            )}
                            <ul className="list-none" role="list">
                                {section.items.map(item => (
                                    <li key={item.id} className="mb-0">
                                        <NavLink
                                            to={item.path}
                                            onClick={handleParentNavLinkClick}
                                            className={`sidebar-nav-link flex items-center gap-3 py-3 px-3 mx-0 my-0.5 rounded-lg no-underline text-sm font-medium transition-all duration-150 touch-target relative ${
                                                item.type === 'parent' && isParentActive(item)
                                                    ? 'sidebar-nav-link--active'
                                                    : ''
                                            } ${
                                                item.type === 'single' && isSingleActive(item.path)
                                                    ? 'sidebar-nav-link--active'
                                                    : ''
                                            }`}
                                            aria-current={
                                                (item.type === 'parent' && isParentActive(item)) ||
                                                (item.type === 'single' &&
                                                    isSingleActive(item.path))
                                                    ? 'page'
                                                    : undefined
                                            }
                                        >
                                            <span
                                                className="text-base flex items-center justify-center w-5 shrink-0 material-symbols-outlined"
                                                aria-hidden="true"
                                            >
                                                {item.icon}
                                            </span>
                                            <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                                {item.label}
                                            </span>
                                        </NavLink>

                                        {item.type === 'parent' &&
                                            item.children &&
                                            isParentActive(item) && (
                                                <ul className="list-none mt-1 mb-1" role="list">
                                                    {item.children.map(child => (
                                                        <li key={child.id} className="mb-0">
                                                            <NavLink
                                                                to={child.path}
                                                                onClick={handleChildNavLinkClick}
                                                                className={`sidebar-nav-link sidebar-nav-link--child flex items-center py-2 pl-12 pr-3 rounded-lg my-0.5 no-underline text-sm font-normal transition-all duration-150 touch-target ${
                                                                    isChildActive(child.path)
                                                                        ? 'sidebar-nav-link--child-active'
                                                                        : ''
                                                                }`}
                                                                aria-current={
                                                                    isChildActive(child.path)
                                                                        ? 'page'
                                                                        : undefined
                                                                }
                                                            >
                                                                <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                                                    {child.label}
                                                                </span>
                                                            </NavLink>
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ))}
                </nav>

                {/* User / logout block anchored to bottom */}
                {user && (
                    <div className="shrink-0 mx-2 mt-2 px-3 py-3 rounded-lg bg-sidebar-hover flex items-center gap-3">
                        <div
                            className="w-9 h-9 rounded-full bg-primary text-on-color flex items-center justify-center text-sm font-semibold shrink-0"
                            aria-hidden="true"
                        >
                            {userInitial}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-on-color truncate">{user}</div>
                            <div className="text-xs text-sidebar-secondary truncate">Signed in</div>
                        </div>
                        <button
                            type="button"
                            onClick={logout}
                            className="w-8 h-8 rounded-lg flex items-center justify-center text-sidebar-secondary hover:text-on-color hover:bg-sidebar-bg transition-colors touch-target"
                            aria-label="Log out"
                            title="Log out"
                        >
                            <span
                                className="material-symbols-outlined text-base"
                                aria-hidden="true"
                            >
                                logout
                            </span>
                        </button>
                    </div>
                )}
            </div>
        </aside>
    );
});

LayoutSidebar.displayName = 'LayoutSidebar';

export default LayoutSidebar;
