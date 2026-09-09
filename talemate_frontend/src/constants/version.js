export const FRONTEND_VERSION = "0.40.0.dev3";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
