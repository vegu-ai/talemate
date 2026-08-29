export const FRONTEND_VERSION = "0.40.0.dev2";

export function versionsMatch(backendVersion) {
  return FRONTEND_VERSION === backendVersion;
}
