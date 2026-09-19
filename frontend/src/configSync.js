export const FRONTEND_CONFIG_REVISION_KEY = 'anyagent.frontend-config-revision'

export function announceFrontendConfig(revision) {
  try {
    window.localStorage.setItem(FRONTEND_CONFIG_REVISION_KEY, revision)
  } catch {
    // Saving the server configuration must not depend on browser storage access.
  }
}
