# Worklog

## 2026-08-16 — Transactional changelog commits

- Made `InMemoryChangelog.commit()` fail-fast and restore changelog artifacts when a required write fails.
- Preserved pending deltas, scene revisions, and message-revision emission until the full commit succeeds.
- Removed the unused unreleased `append_scene_delta` API and migrated retained tests to the supported in-memory path.
- Added failure-injection coverage for base, segment, latest-snapshot, split-segment, and retry behavior.
- Added below-writer failure injection that pins swallowed atomic-replace errors and byte-for-byte restoration of an existing segment.
- Made an in-memory changelog unusable after an incomplete rollback so later saves cannot append an already-written revision twice.
- Clarified that changelog persistence failures abort the current scene save and that retained revisions commit on the next successful save.
