import { useCallback, useEffect, useRef, useState } from "react";
import { api, probeVersion } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../context";
import { fileSize } from "../format";
import type { UpdateStatus } from "../types";

/** Administration > Updates (v0.10.1): install a signed update file without reinstalling. */

type Phase = { kind: "idle" } | { kind: "installing"; from: string; to: string; seconds: number; sawDown: boolean }
  | { kind: "timeout"; to: string };

export default function UpdatesPage() {
  const toast = useToast();
  const [st, setSt] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.updateStatus().then(setSt).catch((e: Error) => toast.error(e.message));
  }, [toast]);
  useEffect(load, [load]);

  // While installing: wait for the app to go away and come back with the new version.
  useEffect(() => {
    if (phase.kind !== "installing") return;
    const t = window.setTimeout(async () => {
      const v = await probeVersion();
      const sawDown = phase.sawDown || v === null;
      const back = v !== null && sawDown;
      if (back && v === phase.to) {
        window.location.reload();  // the new version's screens
        return;
      }
      if (back && v === phase.from && phase.from !== phase.to) {
        window.location.reload();  // rolled back: the page shows what happened
        return;
      }
      if (phase.seconds >= 240) { setPhase({ kind: "timeout", to: phase.to }); return; }
      setPhase({ ...phase, seconds: phase.seconds + 2, sawDown });
    }, 2000);
    return () => window.clearTimeout(t);
  }, [phase]);

  async function choose(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      setSt(await api.uploadUpdate(file));
      toast.success("Update file checked: signed by F&M IT Services and complete.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not read the update file");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function install() {
    if (!st?.staged) return;
    setConfirm(false);
    setBusy(true);
    try {
      const r = await api.applyUpdate();
      setPhase({ kind: "installing", from: st.current_version, to: r.version, seconds: 0, sawDown: false });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start the update");
    } finally {
      setBusy(false);
    }
  }

  if (phase.kind === "installing") {
    return (
      <div className="page">
        <section className="panel update-progress" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <h1>Installing version {phase.to}</h1>
          <p>F&amp;M Finance closes, puts the new version in place and starts again. This page comes back by
            itself, usually within a minute. Don't close this tab or turn off the computer.</p>
          <ol className="update-steps">
            <li className="done">Database and settings backed up</li>
            <li className={phase.sawDown ? "done" : "now"}>Closing the current version</li>
            <li className={phase.sawDown ? "now" : ""}>Starting version {phase.to}</li>
          </ol>
        </section>
      </div>
    );
  }
  if (phase.kind === "timeout") {
    return (
      <div className="page">
        <section className="panel">
          <h1>Still waiting for F&amp;M Finance</h1>
          <p>It's taking longer than expected. If it doesn't open in a minute, start FMFinance.exe yourself. If version
            {" "}{phase.to} couldn't start, the previous version and your database were put back automatically.</p>
          <p className="muted">Details are in the updates\update.log file in the app's folder.</p>
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>Try again</button>
        </section>
      </div>
    );
  }

  const r = st?.last_result;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Updates</h1>
          <p className="page-sub">Install a new version from an update file. Your data, settings and shortcuts stay as they are.</p>
        </div>
      </header>

      {r?.status === "ok" && r.version === st?.current_version && (
        <div className="callout callout-ok">Version {r.version} was installed{r.when ? ` (${r.when})` : ""}.</div>
      )}
      {r?.status === "rolled_back" && (
        <div className="callout callout-error">Version {r.version} didn't start, so the previous version and your database
          were put back automatically. Nothing was lost. Send updates\update.log to F&amp;M IT Services.</div>
      )}
      {r?.status === "not_installed" && (
        <div className="callout callout-warn">Version {r.version} wasn't installed because the app's file couldn't be replaced
          (another copy may have been open). Nothing was changed; you can try again.</div>
      )}

      <section className="panel">
        <div className="facts update-facts">
          <div><span className="muted">Installed version</span><strong>{st?.current_version ?? "…"}</strong></div>
          <div><span className="muted">Program</span><strong>{st?.exe_name ?? "…"}</strong></div>
          <div className="wide"><span className="muted">Folder</span><code>{st?.folder ?? "…"}</code></div>
        </div>
        {st && !st.supported && <div className="callout callout-warn">{st.reason}</div>}
      </section>

      {st?.supported && (
        st.staged ? (
          <section className="panel update-ready">
            <h2>{st.staged.kind === "reinstall" ? `Reinstall version ${st.staged.version}` : `Version ${st.staged.version} is ready to install`}</h2>
            <p className="muted small">Checked: signed by F&amp;M IT Services, complete ({fileSize(st.staged.exe_size)}).
              {st.staged.built_at && ` Built ${st.staged.built_at.slice(0, 10)}.`}</p>
            {st.staged.notes && <div className="update-notes">{st.staged.notes}</div>}
            <ul className="update-checklist">
              <li>Your database and settings are backed up first (the last 5 backups are kept in the backups folder).</li>
              <li>Everyone using F&amp;M Finance on this computer is disconnected for about a minute.</li>
              <li>If the new version doesn't start, the previous one and the database backup are put back automatically.</li>
            </ul>
            <div className="form-actions">
              <button type="button" className="btn" disabled={busy} onClick={() => void api.discardUpdate().then(setSt)}>Remove this file</button>
              <span className="spacer" />
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => setConfirm(true)}>
                {st.staged.kind === "reinstall" ? "Reinstall and restart" : "Install and restart"}</button>
            </div>
          </section>
        ) : (
          <section className="panel">
            <h2>Install an update</h2>
            <p className="muted">Choose the <strong>FMFinance_Update_v….fmupdate</strong> file you received. It's checked before
              anything changes: files that aren't signed by F&amp;M IT Services, are damaged, or are older than this version
              are refused.</p>
            <label className={busy ? "dropzone is-loading" : "dropzone"}>
              <input ref={fileInput} type="file" accept=".fmupdate" className="sr-only" disabled={busy}
                onChange={(e) => void choose(e.target.files?.[0])} />
              <span>{busy ? "Checking the update file…" : "Choose update file"}</span>
            </label>
          </section>
        )
      )}

      {st && st.backups.length > 0 && (
        <section className="panel">
          <h2>Backups made before updates</h2>
          <p className="muted small">In the backups folder next to the app. To go back by hand: stop the app, copy the database
            file from a backup over data\fm_finance.db, and use {st.exe_name.replace(/\.exe$/i, "")}.previous.exe.</p>
          <ul className="plain-list">
            {st.backups.map((b) => <li key={b.name}><code>{b.name}</code> <span className="muted small">{fileSize(b.bytes)}</span></li>)}
          </ul>
        </section>
      )}

      <ConfirmDialog open={confirm} title={st?.staged ? `Install version ${st.staged.version} now?` : "Install?"}
        confirmLabel="Install and restart" message="F&M Finance will close for about a minute and open again by itself."
        onCancel={() => setConfirm(false)} onConfirm={() => void install()} />
    </div>
  );
}
