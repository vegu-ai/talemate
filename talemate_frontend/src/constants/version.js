export const FRONTEND_VERSION = "0.36.1";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
