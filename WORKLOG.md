# Worklog

## 2026-08-20 — Docker fixes port for 0.40

- Pinned the Docker image's uv, corepack, and FFmpeg inputs so toolchain drift cannot break later builds.
- Kept host frontend dependencies and local runtime state out of the Docker build context.
- Added an image-build guard for torchcodec and shipped the Markdown documentation required by the Help agent.

## 2026-08-16 — Transactional changelog commits

- Made `InMemoryChangelog.commit()` fail-fast and restore changelog artifacts when a required write fails.
- Preserved pending deltas, scene revisions, and message-revision emission until the full commit succeeds.
- Removed the unused unreleased `append_scene_delta` API and migrated retained tests to the supported in-memory path.
- Added failure-injection coverage for base, segment, latest-snapshot, split-segment, and retry behavior.
- Added below-writer failure injection that pins swallowed atomic-replace errors and byte-for-byte restoration of an existing segment.
- Made an in-memory changelog unusable after an incomplete rollback so later saves cannot append an already-written revision twice.
- Clarified that changelog persistence failures abort the current scene save and that retained revisions commit on the next successful save.
