import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import { useToast } from '../contexts/ToastContext.jsx';
import { useDocumentTitle } from '../hooks/useDocumentTitle.js';
import { instancesAPI } from '../utils/api/instances.js';
import { configAPI } from '../utils/api/config.js';

// Wizard steps. `optional` steps can be skipped; required steps gate Finish.
const STEPS = [
    { id: 'welcome', title: 'Welcome' },
    { id: 'account', title: 'User account', badge: 'Required' },
    { id: 'plex', title: 'Media Server', badge: 'Required*' },
    { id: 'arr', title: '*arr Instances', badge: 'Required*' },
    { id: 'tmdb', title: 'TMDB API', badge: 'Required' },
    { id: 'gdrive', title: 'Poster Sync', badge: 'Optional', optional: true },
    { id: 'notify', title: 'Notifications', badge: 'Optional', optional: true },
    { id: 'review', title: 'Review' },
];

const ARR_SERVICES = ['radarr', 'sonarr', 'lidarr'];

/** Flatten /api/instances (array OR {radarr:[...],plex:[...]}) to a typed list. */
const normalizeInstances = raw => {
    if (Array.isArray(raw)) {
        return raw.map(i => ({
            service: (i.service || i.type || '').toLowerCase(),
            name: i.name,
            url: i.url,
        }));
    }
    if (raw && typeof raw === 'object') {
        // /api/instances returns each service as a dict keyed by instance name
        // ({radarr: {radarr_main: {...}}}), not an array — flatten both shapes
        // so existing instances hydrate the wizard's Plex/*arr steps.
        return Object.entries(raw).flatMap(([service, entries]) => {
            const rows = Array.isArray(entries)
                ? entries
                : Object.entries(entries || {}).map(([name, detail]) => ({
                      name,
                      ...(detail && typeof detail === 'object' ? detail : {}),
                  }));
            return rows.map(i => ({
                service: service.toLowerCase(),
                name: i.name,
                url: i.url,
            }));
        });
    }
    return [];
};

const SetupWizardPage = () => {
    useDocumentTitle();
    const navigate = useNavigate();
    const toast = useToast();
    const { authConfigured, setup, markSetupComplete } = useAuth();

    const [step, setStep] = useState(0);

    // Account
    const [acctDone, setAcctDone] = useState(false);
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');

    // Instances (plex + arr), each {service, name, url, existing?}
    const [plex, setPlex] = useState([]);
    const [arr, setArr] = useState([]);

    // TMDB
    const [tmdbKey, setTmdbKey] = useState('');
    const [tmdbValid, setTmdbValid] = useState(false);

    // Optional detection
    const [gdriveConfigured, setGdriveConfigured] = useState(false);
    const [notifyConfigured, setNotifyConfigured] = useState(false);

    const [busy, setBusy] = useState(false);
    const [finishing, setFinishing] = useState(false);

    // ── Config-aware detection ───────────────────────────────────────────
    // Account "done" is derived from acctDone || authConfigured wherever needed,
    // so no effect is required to sync it.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const list = normalizeInstances(await instancesAPI.fetchInstances());
                if (!cancelled) {
                    setPlex(
                        list.filter(i => i.service === 'plex').map(i => ({ ...i, existing: true }))
                    );
                    setArr(
                        list
                            .filter(i => ARR_SERVICES.includes(i.service))
                            .map(i => ({ ...i, existing: true }))
                    );
                }
            } catch {
                /* best-effort detection */
            }
            try {
                const res = await configAPI.fetchConfig({ section: 'tmdb' });
                const cfg = res?.data ?? res ?? {};
                const key = cfg.apikey ?? cfg?.tmdb?.apikey ?? '';
                if (!cancelled && key) {
                    setTmdbKey(key);
                    setTmdbValid(true);
                }
            } catch {
                /* ignore */
            }
            try {
                const res = await configAPI.fetchConfig({ section: 'sync_gdrive' });
                const cfg = res?.data ?? res ?? {};
                const g = cfg.sync_gdrive ?? cfg;
                if (!cancelled && (g.token || g.client_id || g.gdrive_sa_location)) {
                    setGdriveConfigured(true);
                }
            } catch {
                /* ignore */
            }
            try {
                const res = await configAPI.fetchConfig({ section: 'notifications' });
                const cfg = res?.data ?? res ?? {};
                const n = cfg.notifications ?? cfg;
                const destinations = Array.isArray(n?.destinations) ? n.destinations : [];
                const configured = destinations.some(d => d?.config?.webhook);
                if (!cancelled && configured) setNotifyConfigured(true);
            } catch {
                /* ignore */
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    // ── Step completion + gate ───────────────────────────────────────────
    const isDone = id => {
        switch (id) {
            case 'account':
                return acctDone || authConfigured === true;
            case 'plex':
                return plex.length > 0;
            case 'arr':
                return arr.length > 0;
            case 'tmdb':
                return tmdbValid;
            case 'gdrive':
                return gdriveConfigured;
            case 'notify':
                return notifyConfigured;
            default:
                return false;
        }
    };

    const requirementsMet =
        (acctDone || authConfigured === true) && (plex.length > 0 || arr.length > 0) && tmdbValid;

    // ── Actions ──────────────────────────────────────────────────────────
    const createAccount = async () => {
        if (!username.trim() || password.length < 8) {
            toast.error('Username required and password must be at least 8 characters');
            return;
        }
        if (password !== confirm) {
            toast.error('Passwords do not match');
            return;
        }
        setBusy(true);
        try {
            await setup(username.trim(), password);
            setAcctDone(true);
            toast.success('Account created');
        } catch (err) {
            toast.error(err.message || 'Failed to create account');
        } finally {
            setBusy(false);
        }
    };

    const addInstance = async (service, form, reset) => {
        const { name, url, api } = form;
        if (!name.trim() || !url.trim()) {
            toast.error('Name and URL are required');
            return;
        }
        setBusy(true);
        try {
            await instancesAPI.testInstanceConfig({
                service,
                name: name.trim(),
                url: url.trim(),
                api,
            });
            await instancesAPI.createInstance({
                service,
                name: name.trim(),
                url: url.trim(),
                api,
                webhook_force_reupload: false,
            });
            const entry = { service, name: name.trim(), url: url.trim() };
            if (service === 'plex') setPlex(p => [...p, entry]);
            else setArr(a => [...a, entry]);
            reset();
            toast.success(`Connected ${name.trim()}`);
        } catch (err) {
            toast.error(err.message || `Could not connect to ${name.trim()}`);
        } finally {
            setBusy(false);
        }
    };

    const saveTmdb = async () => {
        const key = tmdbKey.trim();
        if (key.length < 10) {
            toast.error('Enter a valid TMDB v3 API key');
            return;
        }
        setBusy(true);
        try {
            await configAPI.updateConfig({ tmdb: { apikey: key } });
            setTmdbValid(true);
            toast.success('TMDB key saved');
        } catch (err) {
            toast.error(err.message || 'Failed to save TMDB key');
        } finally {
            setBusy(false);
        }
    };

    const finish = async () => {
        setFinishing(true);
        await markSetupComplete();
        navigate('/dashboard', { replace: true });
    };

    // ── Render ───────────────────────────────────────────────────────────
    const go = i => setStep(Math.max(0, Math.min(STEPS.length - 1, i)));
    const cur = STEPS[step];

    return (
        <div className="sw-page">
            <div className="sw-card">
                <aside className="sw-rail">
                    <div className="sw-brand">
                        <img src="/img/favicon-64x64.png" alt="CHUB" className="sw-logo" />
                        <div>
                            <div className="sw-name">CHUB</div>
                            <div className="sw-sub">First-run setup</div>
                        </div>
                    </div>
                    {STEPS.map((s, i) => {
                        const done = isDone(s.id);
                        return (
                            <button
                                key={s.id}
                                type="button"
                                className={`sw-step${i === step ? ' active' : ''}${done ? ' done' : ''}`}
                                onClick={() => go(i)}
                            >
                                <span className="sw-dot">{done ? '✓' : i + 1}</span>
                                <span className="sw-labels">
                                    <span className="sw-t">{s.title}</span>
                                    {s.badge && (
                                        <span
                                            className={`sw-badge${s.badge.startsWith('Required') ? ' req' : ''}`}
                                        >
                                            {s.badge}
                                        </span>
                                    )}
                                </span>
                            </button>
                        );
                    })}
                </aside>

                <section className="sw-content">
                    <div className="sw-progress">
                        <i style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }} />
                    </div>
                    <div className="sw-panel">
                        {cur.id === 'welcome' && <WelcomeStep authConfigured={authConfigured} />}
                        {cur.id === 'account' && (
                            <AccountStep
                                done={acctDone || authConfigured === true}
                                username={username}
                                password={password}
                                confirm={confirm}
                                setUsername={setUsername}
                                setPassword={setPassword}
                                setConfirm={setConfirm}
                                onCreate={createAccount}
                                busy={busy}
                            />
                        )}
                        {cur.id === 'plex' && (
                            <InstanceStep
                                title="Connect your media server(s)"
                                lead="CHUB uploads posters directly to Plex. Add one or more Plex servers and test each."
                                services={['plex']}
                                list={plex}
                                onAdd={addInstance}
                                onRemove={i => setPlex(p => p.filter((_, idx) => idx !== i))}
                                busy={busy}
                                tokenLabel="Plex token"
                            />
                        )}
                        {cur.id === 'arr' && (
                            <InstanceStep
                                title="Add Radarr / Sonarr / Lidarr"
                                lead="CHUB reads your *arr libraries to know what media exists and where its files live."
                                services={ARR_SERVICES}
                                list={arr}
                                onAdd={addInstance}
                                onRemove={i => setArr(a => a.filter((_, idx) => idx !== i))}
                                busy={busy}
                                tokenLabel="API key"
                            />
                        )}
                        {cur.id === 'tmdb' && (
                            <TmdbStep
                                value={tmdbKey}
                                valid={tmdbValid}
                                onChange={setTmdbKey}
                                onSave={saveTmdb}
                                busy={busy}
                            />
                        )}
                        {cur.id === 'gdrive' && (
                            <OptionalStep
                                title="Poster drive sync"
                                lead="Sync poster source drives (community drives or your own Google Drive) so the renamer always has artwork. Skip if you only apply posters you already have."
                                configured={gdriveConfigured}
                                cta="Open Drive sync settings"
                                onCta={() => navigate('/settings/modules')}
                            />
                        )}
                        {cur.id === 'notify' && (
                            <OptionalStep
                                title="Notifications"
                                lead="Get pinged when jobs finish, or globally on errors, via Discord or Notifiarr."
                                configured={notifyConfigured}
                                cta="Open Notification settings"
                                onCta={() => navigate('/settings/notifications')}
                            />
                        )}
                        {cur.id === 'review' && (
                            <ReviewStep
                                account={acctDone || authConfigured === true}
                                username={username}
                                plex={plex}
                                arr={arr}
                                tmdb={tmdbValid}
                                gdrive={gdriveConfigured}
                                notify={notifyConfigured}
                            />
                        )}
                    </div>

                    <div className="sw-nav">
                        <button
                            type="button"
                            className="sw-btn ghost"
                            onClick={() => go(step - 1)}
                            disabled={step === 0 || finishing}
                        >
                            Back
                        </button>
                        <div className="sw-grow">
                            {cur.id === 'review' && (
                                <span className={`sw-gate${requirementsMet ? ' met' : ''}`}>
                                    {requirementsMet
                                        ? '✓ Minimum configuration met'
                                        : 'Need: user account · Plex or an *arr · TMDB key'}
                                </span>
                            )}
                        </div>
                        {cur.optional && (
                            <button
                                type="button"
                                className="sw-btn ghost"
                                onClick={() => go(step + 1)}
                                disabled={finishing}
                            >
                                Skip
                            </button>
                        )}
                        {cur.id === 'review' ? (
                            <button
                                type="button"
                                className="sw-btn"
                                onClick={finish}
                                disabled={!requirementsMet || finishing}
                            >
                                {finishing ? 'Finishing…' : 'Finish setup →'}
                            </button>
                        ) : (
                            <button
                                type="button"
                                className="sw-btn"
                                onClick={() => go(step + 1)}
                                disabled={finishing}
                            >
                                Next →
                            </button>
                        )}
                    </div>
                </section>
            </div>
            <WizardStyles />
        </div>
    );
};

// ── Step components ──────────────────────────────────────────────────────
const WelcomeStep = ({ authConfigured }) => (
    <>
        <h2>Welcome to CHUB</h2>
        <p className="sw-lead">
            CHUB renames, sources, and applies your media artwork automatically. This takes about
            two minutes — anything here can be changed later in Settings.
        </p>
        <div className="sw-callout info">
            {authConfigured
                ? 'Re-running setup — we’ve pre-filled what’s already configured. Review and adjust anything you like.'
                : 'Already ran DAPS? Drop your old config.yml in the config dir and restart — CHUB migrates it automatically, then this wizard just confirms what came across.'}
        </div>
    </>
);

const AccountStep = ({
    done,
    username,
    password,
    confirm,
    setUsername,
    setPassword,
    setConfirm,
    onCreate,
    busy,
}) => (
    <>
        <h2>Create your user account</h2>
        <p className="sw-lead">
            CHUB is protected by a single user login, stored locally (bcrypt-hashed) — no account or
            cloud service involved.
        </p>
        {done ? (
            <div className="sw-callout ok">✓ User account is configured.</div>
        ) : (
            <>
                <label className="sw-fld">
                    <span>Username</span>
                    <input
                        type="text"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        autoComplete="username"
                    />
                </label>
                <div className="sw-row">
                    <label className="sw-fld">
                        <span>Password</span>
                        <input
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            autoComplete="new-password"
                        />
                    </label>
                    <label className="sw-fld">
                        <span>Confirm password</span>
                        <input
                            type="password"
                            value={confirm}
                            onChange={e => setConfirm(e.target.value)}
                            autoComplete="new-password"
                        />
                    </label>
                </div>
                <button
                    type="button"
                    className="sw-btn secondary"
                    onClick={onCreate}
                    disabled={busy}
                >
                    {busy ? 'Creating…' : 'Create account'}
                </button>
            </>
        )}
    </>
);

const InstanceStep = ({ title, lead, services, list, onAdd, onRemove, busy, tokenLabel }) => {
    const [service, setService] = useState(services[0]);
    const [name, setName] = useState('');
    const [url, setUrl] = useState('');
    const [api, setApi] = useState('');
    const reset = () => {
        setName('');
        setUrl('');
        setApi('');
    };
    return (
        <>
            <h2>{title}</h2>
            <p className="sw-lead">{lead}</p>
            {services.length > 1 ? (
                <div className="sw-row">
                    <label className="sw-fld">
                        <span>Type</span>
                        <select value={service} onChange={e => setService(e.target.value)}>
                            {services.map(s => (
                                <option key={s} value={s}>
                                    {s.charAt(0).toUpperCase() + s.slice(1)}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="sw-fld">
                        <span>Name</span>
                        <input type="text" value={name} onChange={e => setName(e.target.value)} />
                    </label>
                </div>
            ) : (
                <label className="sw-fld">
                    <span>Name</span>
                    <input type="text" value={name} onChange={e => setName(e.target.value)} />
                </label>
            )}
            <div className="sw-row">
                <label className="sw-fld">
                    <span>URL</span>
                    <input
                        type="url"
                        value={url}
                        onChange={e => setUrl(e.target.value)}
                        placeholder="http://192.168.1.10:7878"
                    />
                </label>
                <label className="sw-fld">
                    <span>{tokenLabel}</span>
                    <input type="password" value={api} onChange={e => setApi(e.target.value)} />
                </label>
            </div>
            <button
                type="button"
                className="sw-btn secondary"
                onClick={() => onAdd(service, { name, url, api }, reset)}
                disabled={busy}
            >
                {busy ? 'Testing…' : 'Test & add'}
            </button>
            <div className="sw-list">
                {list.map((inst, i) => (
                    <div className="sw-inst" key={`${inst.service}-${inst.name}-${i}`}>
                        <span className="sw-tag">{inst.service}</span>
                        <span className="sw-meta">
                            <b>
                                {inst.name}
                                {inst.existing ? ' · existing' : ''}
                            </b>
                            <small>{inst.url}</small>
                        </span>
                        <button
                            type="button"
                            className="sw-rm"
                            onClick={() => onRemove(i)}
                            title="Remove from this list"
                        >
                            ✕
                        </button>
                    </div>
                ))}
            </div>
        </>
    );
};

const TmdbStep = ({ value, valid, onChange, onSave, busy }) => (
    <>
        <h2>TMDB API key</h2>
        <p className="sw-lead">
            CHUB uses The Movie Database to match titles, fetch metadata, and source artwork. A free
            API key takes a minute to create at themoviedb.org → Settings → API.
        </p>
        {valid && <div className="sw-callout ok">✓ TMDB key is in place.</div>}
        <label className="sw-fld">
            <span>TMDB API key (v3)</span>
            <input type="text" value={value} onChange={e => onChange(e.target.value)} />
        </label>
        <button type="button" className="sw-btn secondary" onClick={onSave} disabled={busy}>
            {busy ? 'Saving…' : 'Validate & save'}
        </button>
    </>
);

const OptionalStep = ({ title, lead, configured, cta, onCta }) => (
    <>
        <h2>
            {title} <span className="sw-opt">(optional)</span>
        </h2>
        <p className="sw-lead">{lead}</p>
        <div className={`sw-callout ${configured ? 'ok' : 'info'}`}>
            {configured
                ? '✓ Already configured — open settings to review or change it.'
                : 'Not set up yet. You can configure this now or skip and do it later.'}
        </div>
        <button type="button" className="sw-btn secondary" onClick={onCta}>
            {cta}
        </button>
    </>
);

const ReviewStep = ({ account, username, plex, arr, tmdb, gdrive, notify }) => {
    const rows = useMemo(
        () => [
            ['User account', account, account ? username || 'configured' : 'Not created'],
            [
                'Media server (Plex)',
                plex.length > 0,
                plex.length ? plex.map(p => p.name).join(', ') : 'Skipped',
            ],
            [
                '*arr instances',
                arr.length > 0,
                arr.length ? arr.map(a => a.name).join(', ') : 'None added',
            ],
            ['TMDB API key', tmdb, tmdb ? 'In place' : 'Not set'],
            ['Poster drive sync', gdrive, gdrive ? 'Configured' : 'Skipped'],
            ['Notifications', notify, notify ? 'Configured' : 'Skipped'],
        ],
        [account, username, plex, arr, tmdb, gdrive, notify]
    );
    return (
        <>
            <h2>Review &amp; finish</h2>
            <p className="sw-lead">
                Here’s what CHUB will start with. Anything skipped can be added later from Settings.
            </p>
            <div className="sw-review">
                {rows.map(([label, ok, sub]) => (
                    <div className={`sw-rev${ok ? ' ok' : ''}`} key={label}>
                        <span className="sw-ic">{ok ? '✓' : '–'}</span>
                        <span className="sw-meta">
                            <b>{label}</b>
                            <small>{sub}</small>
                        </span>
                    </div>
                ))}
            </div>
        </>
    );
};

// ── Scoped styles (CHUB tokens, no utility-class dependency) ──────────────
const WizardStyles = () => (
    <style>{`
        .sw-page { display:flex; align-items:center; justify-content:center; min-height:100vh; background:var(--bg); padding:1.5rem; }
        .sw-card { width:100%; max-width:1000px; display:grid; grid-template-columns:270px 1fr; background:var(--surface); border:1px solid var(--border-light); border-radius:var(--radius-xl,24px); overflow:hidden; min-height:600px; }
        .sw-rail { background:var(--sidebar-bg); padding:1.5rem 1.25rem; display:flex; flex-direction:column; gap:.2rem; border-right:1px solid var(--border-light); }
        .sw-brand { display:flex; align-items:center; gap:.65rem; margin-bottom:1.3rem; }
        .sw-logo { width:40px; height:40px; border-radius:10px; }
        .sw-name { font-family:var(--font-display); font-weight:800; font-size:1.18rem; color:var(--text-primary); }
        .sw-sub { font-size:.7rem; color:var(--text-tertiary); }
        .sw-step { display:flex; align-items:center; gap:.7rem; padding:.55rem .7rem; border-radius:var(--radius-md,12px); cursor:pointer; border:1px solid transparent; background:transparent; text-align:left; font-family:inherit; }
        .sw-step:hover { background:var(--surface-alt); }
        .sw-step.active { background:color-mix(in srgb, var(--primary) 22%, transparent); border-color:color-mix(in srgb, var(--primary) 45%, transparent); }
        .sw-dot { width:26px; height:26px; flex:none; border-radius:50%; display:grid; place-items:center; font-size:.78rem; font-weight:600; background:var(--surface-alt); color:var(--text-secondary); border:1px solid var(--border); }
        .sw-step.active .sw-dot { background:var(--primary); color:#fff; border-color:var(--primary); }
        .sw-step.done .sw-dot { background:var(--success); color:#07210a; border-color:var(--success); }
        .sw-labels { display:flex; flex-direction:column; min-width:0; }
        .sw-t { font-size:.86rem; font-weight:600; color:var(--text-primary); }
        .sw-badge { font-size:.62rem; text-transform:uppercase; letter-spacing:.06em; color:var(--text-tertiary); }
        .sw-badge.req { color:var(--warning); }
        .sw-content { display:flex; flex-direction:column; padding:1.75rem 2.25rem 2rem; }
        .sw-progress { height:4px; background:var(--surface-alt); border-radius:999px; overflow:hidden; margin-bottom:1.3rem; }
        .sw-progress > i { display:block; height:100%; background:linear-gradient(90deg, var(--primary), var(--accent)); transition:width .35s ease; }
        .sw-panel { flex:1; }
        .sw-panel h2 { font-family:var(--font-display); font-size:1.5rem; color:var(--text-primary); margin:0 0 .4rem; }
        .sw-lead { color:var(--text-secondary); line-height:1.55; margin:0 0 1.4rem; max-width:54ch; }
        .sw-opt { font-size:.8rem; color:var(--text-tertiary); }
        .sw-fld { display:block; margin-bottom:1rem; }
        .sw-fld > span { display:block; font-size:.8125rem; font-weight:500; color:var(--text-secondary); margin-bottom:.375rem; }
        .sw-fld input, .sw-fld select { width:100%; height:44px; padding:0 .75rem; background:var(--input-bg); color:var(--text-primary); border:1px solid var(--border); border-radius:var(--radius-md,12px); font-family:inherit; font-size:.95rem; box-sizing:border-box; }
        .sw-fld input:focus, .sw-fld select:focus { outline:none; border-color:var(--primary); box-shadow:0 0 0 3px color-mix(in srgb, var(--primary) 22%, transparent); }
        .sw-row { display:grid; grid-template-columns:1fr 1fr; gap:.9rem; }
        .sw-row3 { display:grid; grid-template-columns:1fr 1fr 130px; gap:.9rem; }
        .sw-fld-btn .sw-btn { width:100%; }
        .sw-btn { font-family:inherit; font-size:.9rem; font-weight:600; height:44px; padding:0 1.1rem; border-radius:var(--radius-md,12px); border:none; cursor:pointer; background:var(--primary); color:#fff; }
        .sw-btn:hover:not(:disabled) { background:var(--primary-hover); }
        .sw-btn:disabled { opacity:.45; cursor:not-allowed; }
        .sw-btn.secondary { background:var(--surface-alt); color:var(--text-primary); }
        .sw-btn.ghost { background:transparent; color:var(--text-secondary); border:1px solid var(--border); }
        .sw-btn.ghost:hover:not(:disabled) { color:var(--text-primary); border-color:var(--primary); }
        .sw-callout { padding:.85rem 1rem; border-radius:var(--radius-md,12px); font-size:.83rem; color:var(--text-secondary); margin-bottom:1.2rem; }
        .sw-callout.info { background:color-mix(in srgb, var(--accent) 10%, transparent); border:1px solid color-mix(in srgb, var(--accent) 30%, transparent); }
        .sw-callout.ok { background:color-mix(in srgb, var(--success) 12%, transparent); border:1px solid color-mix(in srgb, var(--success) 32%, transparent); }
        .sw-list { display:flex; flex-direction:column; gap:.5rem; margin-top:1rem; }
        .sw-inst { display:flex; align-items:center; gap:.7rem; padding:.7rem .9rem; border-radius:var(--radius-md,12px); background:var(--input-bg); border:1px solid var(--border-light); }
        .sw-tag { font-size:.65rem; text-transform:uppercase; letter-spacing:.05em; padding:.15rem .5rem; border-radius:999px; background:color-mix(in srgb, var(--accent) 22%, transparent); color:var(--accent); font-weight:700; }
        .sw-meta { flex:1; min-width:0; }
        .sw-meta b { font-size:.9rem; color:var(--text-primary); }
        .sw-meta small { display:block; color:var(--text-tertiary); font-size:.74rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .sw-rm { background:transparent; border:none; color:var(--text-tertiary); cursor:pointer; font-size:1.1rem; }
        .sw-rm:hover { color:var(--error); }
        .sw-review { display:flex; flex-direction:column; gap:.55rem; }
        .sw-rev { display:flex; align-items:center; gap:.7rem; padding:.7rem .9rem; border-radius:var(--radius-md,12px); background:var(--input-bg); border:1px solid var(--border-light); }
        .sw-ic { width:24px; height:24px; border-radius:50%; display:grid; place-items:center; font-size:.8rem; flex:none; background:var(--surface-alt); color:var(--text-tertiary); }
        .sw-rev.ok .sw-ic { background:color-mix(in srgb, var(--success) 25%, transparent); color:var(--success); }
        .sw-nav { display:flex; align-items:center; gap:.6rem; margin-top:1.5rem; padding-top:1.25rem; border-top:1px solid var(--border); }
        .sw-grow { flex:1; }
        .sw-gate { font-size:.76rem; color:var(--text-tertiary); }
        .sw-gate.met { color:var(--success); }
        @media (max-width:780px) {
            .sw-card { grid-template-columns:1fr; }
            .sw-rail { flex-direction:row; overflow-x:auto; border-right:none; border-bottom:1px solid var(--border-light); }
            .sw-labels, .sw-sub { display:none; }
            .sw-row, .sw-row3 { grid-template-columns:1fr; }
        }
    `}</style>
);

export default SetupWizardPage;
