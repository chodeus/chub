// "Test connection" for the CL2K AI provider — the custom settings field type
// `cl2k_ai_test` (registered in manifest.jsx).
//
// Sends NO credentials: GET /api/config serves api_key/client_key redacted, so
// the browser never holds the real ones and the endpoint reads them server-side.
// Consequence worth surfacing to the user: it tests SAVED settings, not unsaved
// edits.
import React, { useCallback, useState } from 'react';
import { apiCore } from '../../utils/api/core';
import { useToast } from '../../contexts/ToastContext.jsx';

export const Cl2kAiTestField = ({ rootConfig }) => {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null); // { ok, message }
    const provider = rootConfig?.cl2k_maker?.ai_provider || 'none';

    const run = useCallback(async () => {
        setBusy(true);
        setResult(null);
        try {
            const res = await apiCore.post('/cl2k-maker/test-ai', {});
            const message = res?.message || 'Connection works';
            setResult({ ok: true, message });
            toast.success(message);
        } catch (e) {
            const message = e?.message || 'Connection test failed';
            setResult({ ok: false, message });
            toast.error(message);
        } finally {
            setBusy(false);
        }
    }, [toast]);

    return (
        <div className="flex flex-col gap-2">
            <p className="text-[12px] leading-[1.45] text-fg-subtle -mt-3 m-0">
                Round-trips the provider&apos;s authenticated route using your saved settings — save
                first if you have just changed the key.
            </p>
            <div>
                <button
                    type="button"
                    onClick={run}
                    disabled={busy || provider === 'none'}
                    title={provider === 'none' ? 'Choose an AI provider first' : undefined}
                    className="inline-flex items-center gap-1.5 h-[38px] px-3 shrink-0 bg-surface border border-border rounded-lg text-fg-muted text-[12.5px] font-medium hover:text-fg hover:border-primary/50 disabled:opacity-50 transition-colors"
                >
                    <span
                        className="material-symbols-outlined leading-none select-none text-[16px] text-accent"
                        aria-hidden="true"
                    >
                        lan
                    </span>
                    {busy ? 'Testing…' : 'Test connection'}
                </button>
            </div>
            {result && (
                <p
                    className={`text-[12px] leading-[1.45] m-0 ${
                        result.ok ? 'text-fg-muted' : 'text-warning'
                    }`}
                >
                    {result.message}
                </p>
            )}
        </div>
    );
};
