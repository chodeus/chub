import { useState, useEffect } from 'react';
import { logsAPI } from '../utils/api/logs.js';

/** Log files for a module, auto-selecting `{module}.log` when present, else the first. */
export function useLogFiles(selectedModule) {
    const [logFiles, setLogFiles] = useState([]);
    const [selectedLogFile, setSelectedLogFile] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        let isMounted = true;

        async function loadFiles() {
            if (!selectedModule) {
                setLogFiles([]);
                setSelectedLogFile('');
                setLoading(false);
                return;
            }

            try {
                setLoading(true);
                setError(null);

                const files = await logsAPI.fetchLogFiles(selectedModule);

                if (!isMounted) return;

                setLogFiles(files);

                // Auto-select default file: prefer {module}.log, otherwise first file
                const defaultLog = files.find(f => f === `${selectedModule}.log`) || files[0] || '';
                setSelectedLogFile(defaultLog);
            } catch (err) {
                if (!isMounted) return;
                console.error('Failed to fetch log files:', err);
                setError(err);
                setLogFiles([]);
                setSelectedLogFile('');
            } finally {
                if (isMounted) {
                    setLoading(false);
                }
            }
        }

        loadFiles();

        return () => {
            isMounted = false;
        };
    }, [selectedModule]);

    return {
        logFiles,
        selectedLogFile,
        setSelectedLogFile,
        loading,
        error,
    };
}
