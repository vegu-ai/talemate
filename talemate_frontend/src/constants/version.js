export const FRONTEND_VERSION = "0.36.0.dev1";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
