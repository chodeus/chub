// Read-only Module Settings strip: which save locations the healer assesses for
// id/title/year drift. Carries no config value — it never calls onChange, so its
// key never lands in formData. Renders INSIDE ModuleSettingsPage's own section
// card, so it must not draw a second outer card.
import React, { useEffect, useState } from 'react';
import { posterSelfHealAPI } from '../../utils/api/posterSelfHeal.js';

const TYPE_LABEL = {
    poster: 'Poster',
    logo: 'Logo',
    background: 'Background',
    squareart: 'Square Art',
};

const Icon = ({ name, className = '' }) => (
    <span
        className={`material-symbols-outlined leading-none select-none ${className}`}
        aria-hidden="true"
    >
        {name}
    </span>
);

const Pills = ({ types, muted }) =>
    types.length === 0 ? (
        <span className="text-[11px] text-fg-dim italic">nothing routed</span>
    ) : (
        <span className="flex items-center gap-[5px] flex-wrap">
            {types.map(t => (
                <span
                    key={t}
                    className={`inline-flex items-center h-[22px] px-2 rounded-full text-[11px] font-medium ${
                        muted ? 'bg-surface text-fg-subtle' : 'bg-primary/15 text-primary'
                    }`}
                >
                    {TYPE_LABEL[t] || t}
                </span>
            ))}
        </span>
    );

const Row = ({ icon, iconClass, name, value, types, muted }) => (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 rounded-[9px] bg-surface-inset border border-border-light">
        <Icon name={icon} className={`text-[17px] ${iconClass}`} />
        <span className="text-[12.5px] font-medium text-fg">{name || 'Unnamed'}</span>
        <span className="font-mono text-[11.5px] text-fg-muted break-all">{value}</span>
        <span className="ml-auto">
            <Pills types={types} muted={muted} />
        </span>
    </div>
);

export const PosterSelfHealCoverageField = () => {
    const [cov, setCov] = useState(null);
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        (async () => {
            try {
                const res = await posterSelfHealAPI.coverage({ signal: controller.signal });
                if (active) setCov(res?.data || null);
            } catch (err) {
                if (active && err?.name !== 'AbortError')
                    setError(err?.message || 'Could not read the healer’s coverage');
            }
        })();
        return () => {
            active = false;
            controller.abort();
        };
    }, []);

    if (error) {
        return <p className="text-[12px] text-warning -mt-3 m-0">{error}</p>;
    }
    if (!cov) {
        return <p className="text-[12px] text-fg-subtle -mt-3 m-0">Reading save locations…</p>;
    }

    const folders = cov.folders || [];
    const drives = cov.drives || [];
    const unrouted = cov.unrouted_types || [];

    if (!cov.available) {
        return (
            <p className="text-[12px] text-fg-subtle -mt-3 m-0">
                The CL2K Maker extension isn’t available, so nothing is being assessed.
            </p>
        );
    }

    return (
        <div>
            <p className="text-[12px] leading-[1.45] text-fg-subtle -mt-3 mb-2.5 m-0">
                Every run assesses these for id, title and year drift. They come straight from CL2K
                Maker’s save locations — change them there and the next run follows.
            </p>
            {folders.length === 0 && drives.length === 0 ? (
                <p className="text-[12px] text-warning m-0">
                    No save locations are configured, so the healer has nothing to assess.
                </p>
            ) : (
                <div className="flex flex-col gap-1.5">
                    {folders.map(f => (
                        <Row
                            key={f.path}
                            icon="folder"
                            iconClass="text-source-local"
                            name={f.name}
                            value={f.path}
                            types={f.types || []}
                            muted
                        />
                    ))}
                    {drives.map(d => (
                        <Row
                            key={d.folder_id}
                            icon="cloud"
                            iconClass="text-source-gdrive"
                            name={d.name}
                            value={d.folder_id}
                            types={d.heals_types || []}
                        />
                    ))}
                </div>
            )}
            <p className="text-[11.5px] text-fg-subtle mt-2.5 m-0">
                Folder tags show what CL2K saves there; Drive tags show which types are renamed in
                that Drive. A folder claiming no types is still assessed.
            </p>
            {unrouted.length > 0 && (
                <p className="flex items-start gap-1.5 text-[11.5px] text-warning mt-1.5 m-0">
                    <Icon name="info" className="text-[15px] leading-[1.3]" />
                    <span>
                        No Drive receives {unrouted.map(t => TYPE_LABEL[t] || t).join(', ')} art —
                        those heal locally only, so anyone syncing your Drive keeps the old names.
                    </span>
                </p>
            )}
        </div>
    );
};

export default PosterSelfHealCoverageField;
