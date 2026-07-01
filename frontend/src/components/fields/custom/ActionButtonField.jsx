import { useState, useCallback } from 'react';
import { FieldWrapper, FieldLabel, FieldDescription } from '../primitives';
import { Button } from '../../ui';
import { apiCore } from '../../../utils/api/core';
import { useToast } from '../../../contexts/ToastContext.jsx';

/**
 * Generic action-button settings field. Renders a button that POSTs to a
 * configured endpoint and reports the result inline (and via toast). Carries
 * no data of its own — `value`/`onChange` are ignored.
 *
 * field config:
 *   endpoint      — API path to POST to (required)
 *   buttonText    — button label (default "Test")
 *   payloadFields — keys copied from the row (rowData) into the POST body
 *   requireFields — keys that must be non-empty on the row before enabling
 *   requireHint   — text shown when requireFields are unmet
 *
 * When used as an object_array sub-field, ArrayObjectField passes the row via
 * `rowData` so the button can send that row's values (e.g. its folder id).
 */
export const ActionButtonField = ({ field, rowData = null, disabled = false }) => {
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null); // { ok, message }
    const toast = useToast();

    const missing = (field.requireFields || []).filter(
        k => !((rowData || {})[k] ?? '').toString().trim()
    );
    const canRun = !disabled && !busy && !!field.endpoint && missing.length === 0;

    const run = useCallback(async () => {
        setBusy(true);
        setResult(null);
        try {
            const src = rowData || {};
            const payload = {};
            (field.payloadFields || []).forEach(k => {
                payload[k] = src[k];
            });
            const res = await apiCore.post(field.endpoint, payload);
            const msg = res?.message || 'Success';
            setResult({ ok: true, message: msg });
            toast.success(msg);
        } catch (e) {
            const msg = e?.message || 'Request failed';
            setResult({ ok: false, message: msg });
            toast.error(msg);
        } finally {
            setBusy(false);
        }
    }, [field.endpoint, field.payloadFields, rowData, toast]);

    const inputId = `field-${field.key}`;
    return (
        <FieldWrapper variant="standard">
            {field.label && <FieldLabel label={field.label} />}
            <div className="flex items-center gap-3 flex-wrap">
                <Button variant="surface" size="small" onClick={run} disabled={!canRun}>
                    {busy ? 'Testing…' : field.buttonText || 'Test'}
                </Button>
                {result && (
                    <span className={`text-xs ${result.ok ? 'text-success' : 'text-error'}`}>
                        {result.message}
                    </span>
                )}
                {!result && missing.length > 0 && (
                    <span className="text-xs text-fg-subtle">
                        {field.requireHint || 'Fill the required fields first'}
                    </span>
                )}
            </div>
            <FieldDescription id={`${inputId}-description`} description={field.description} />
        </FieldWrapper>
    );
};

ActionButtonField.displayName = 'ActionButtonField';
