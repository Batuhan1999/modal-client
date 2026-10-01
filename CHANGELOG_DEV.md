# SDK development changelogs

User-facing updates in the current development versions of our SDKs are tracked here.

Draft releases notes should be added as part of the PR introducing the change. During a release, the notes are moved to the language-specific `CHANGELOG.md` files and edited for publication.

## Python

- Fixed a bug where Apps with many distinct local mounts (for example, `Image.add_local_dir` per Function) started threads in proportion to the number of mounts while uploading them, which could fail with `RuntimeError: can't start new thread`. Mounts uploaded at the same time now share one bounded thread pool.
- Added `modal endpoint info` command for displaying information such as an endpoint's deployment status, URL, and model id. We've also added `modal endpoint stats` to inspect performance metrics for an Endpoint over a selected time window and `modal endpoint logs` for displaying logs for an Endpoint.

## JS

- Added `client.Functions.FromID()` to look up a Function by ID.

## Go

- Added `client.Functions.FromID` to look up a Function by ID.
