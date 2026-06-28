export const FRONTEND_VERSION = "0.38.0";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
