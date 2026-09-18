/** Aggregated API client exports. */

import { apiCore, APIError } from './core.js';
import { configAPI } from './config.js';
import { modulesAPI } from './modules.js';
import { jobsAPI } from './jobs.js';
import { instancesAPI } from './instances.js';
import { mediaAPI } from './media.js';
import { postersAPI } from './posters.js';
import { logsAPI } from './logs.js';
import { systemAPI } from './system.js';
import { scheduleAPI } from './schedule.js';
import { notificationsAPI } from './notifications.js';
import { labelarrAPI } from './labelarr.js';
import { nestarrAPI } from './nestarr.js';
import { webhooksAPI } from './webhooks.js';

// Re-export the clients below. Others (border_replacerr, cl2k_maker,
// posterSelfHeal, streamAuth) are imported directly from their modules.
export { apiCore, APIError };
export { configAPI };
export { modulesAPI };
export { jobsAPI };
export { instancesAPI };
export { mediaAPI };
export { postersAPI };
export { logsAPI };
export { systemAPI };
export { scheduleAPI };
export { notificationsAPI };
export { labelarrAPI };
export { nestarrAPI };
export { webhooksAPI };

/** The clients above, reachable through one object. Not an exhaustive API index. */
export const api = {
    core: apiCore,
    config: configAPI,
    modules: modulesAPI,
    jobs: jobsAPI,
    instances: instancesAPI,
    media: mediaAPI,
    posters: postersAPI,
    logs: logsAPI,
    system: systemAPI,
    schedule: scheduleAPI,
    notifications: notificationsAPI,
    labelarr: labelarrAPI,
    nestarr: nestarrAPI,
    webhooks: webhooksAPI,
};

export default api;
