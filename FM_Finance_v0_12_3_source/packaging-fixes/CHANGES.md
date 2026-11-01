# Packaging fixes for F&M Finance v0.12.3

No source or packaging fixes were required during the v0.12.3 build and verification.

The original source was used unchanged. The Windows build, 197 passing tests with 1 skipped test, packaged self-test, health checks, v0.12.3 reinstall, rollback, and backup restore all completed successfully.

The v0.12.2-to-v0.12.3 updater test did not restart because that step uses the older v0.12.2 helper. As directed in the build handoff, nothing was patched for that older helper.
