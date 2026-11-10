// The delete endpoints list removed and failed ids: a failure must not read as a success.
export const showDeleteOutcome = (toast, data, doneText) => {
    const failed = data?.failed ?? [];
    if (!failed.length) {
        toast.success(doneText);
        return;
    }
    const removed = data?.removed?.length ?? 0;
    const reasons = [...new Set(failed.map(f => f.reason).filter(Boolean))].join('; ');
    toast.error(`Deleted ${removed}, ${failed.length} not deleted${reasons ? `: ${reasons}` : ''}`);
};
