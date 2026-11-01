# F&M Finance v0.12.3: build handoff for ChatGPT

I'm attaching FM_Finance_v0_12_3_source.zip (v0.12.2 plus two updater fixes). The source has been reviewed and
tested. Your job is packaging and build verification: do NOT change application code (backend/app,
frontend/src, backend/alembic, backend/tests).

## New rule: fixes go back into the source
In v0.10.1 you fixed two updater problems during the build, but the fixes stayed in the build only and were
missing from v0.11.0 through v0.12.2. From now on:
- If anything needs fixing to build or test, STOP and show me the exact error and the exact change you
  propose, file by file, before applying it.
- Every change you apply must be in the source you deliver, listed in packaging-fixes\CHANGES.md with the
  file name and a diff. Never patch only the built EXE or a temporary copy.

## Protect my real data (important since v0.12.2)
Every F&M Finance EXE now keeps its data in %LOCALAPPDATA%\FM Finance. For ALL tests below, first set
FM_FINANCE_DATA_HOME to a test folder (e.g. C:\Temp\FMF-test-data), in the same window or process that starts
the EXE, so test copies never open my real data. Check DATA_LOCATION.txt next to each test EXE: it must show
the test folder. Don't touch my running installation.

## Build (same process as v0.12.2)
1. 64-bit Python 3.12, Node 20+. `npm ci`, `npm run build`. No dependency changes.
2. requirements-portable.txt exactly as pinned, plus pyinstaller==6.22.3, pytest==8.3.4, httpx==0.28.1.
3. Tests: expected 197 passed, 1 skipped (SQLite).
4. packaging\build_portable.bat: keygen refresh (my signing key is already at
   %USERPROFILE%\.fmfinance\update_signing_key.pem; never use --force), EXE, then the signed and verified
   update-output\FMFinance_Update_v0.12.3.fmupdate.
5. `FMFinance.exe --selftest` writes selftest.txt starting with PASS.
6. /api/health shows 0.12.3; GET /api/health/version returns `fm-finance:0.12.3:ok` followed by a newline.
Version is 0.12.3 everywhere. Don't change it.

## Updater tests (in a test folder, with FM_FINANCE_DATA_HOME set as above)
a) Upgrade from v0.12.2: start a copy of the v0.12.2 EXE in the test folder, sign in, Administration > Updates,
   upload FMFinance_Update_v0.12.3.fmupdate and install. NOTE: this step is carried out by v0.12.2's helper,
   which doesn't have the fixes. If it works, good. If it doesn't, report the last lines of updates\update.log
   and updates\last_result.txt, and don't patch anything for it: in that case I'll install v0.12.3 by hand once,
   and from v0.12.3 on the fixed helper does the work.
b) Reinstall with the fixed helper: in the v0.12.3 test copy, upload the same v0.12.3 file again and
   "Reinstall and restart". Expected: the app comes back by itself within about a minute, Updates shows
   "Version 0.12.3 was installed", last_result.txt says status=ok.
c) Roll-back: `python packaging\make_update.py build --version 0.12.99 --out update-test`, upload and install.
   Expected: after about 2 minutes the previous program and database are put back and status=rolled_back.
   Delete update-test afterwards; never ship it.
d) Backup restore: Administration > Backups, make a backup, then restore it. The app must come back by itself
   (restores use the same fixed helper launch).
Report each with what you saw and the last lines of updates\update.log.

## GitHub
Add the source as FM_Finance_v0_12_3_source to frankmorales222-hue/Expense-Application the same way you
added v0.12.2, including packaging-fixes\CHANGES.md if there are any changes.

## Deliverables
portable-output\FMFinance.exe, update-output\FMFinance_Update_v0.12.3.fmupdate, build log, test summary,
selftest.txt, results of a) to d), packaging-fixes\CHANGES.md (or "no changes"), and the GitHub commit link.
