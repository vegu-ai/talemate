export const FRONTEND_VERSION = "0.40.1";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
