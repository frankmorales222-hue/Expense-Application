import { useCallback, useEffect, useState } from "react";
import { api, probeVersion } from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../context";
import { fileSize, formatDateTime } from "../format";
import type { BackupInfo, BackupStatus } from "../types";

type Phase = { kind: "idle" } | { kind: "restoring"; seconds: number; sawDown: boolean } | { kind: "timeout" };

export default function BackupsPage() {
  const toast = useToast();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<BackupInfo | null>(null);
  const [restoreSettings, setRestoreSettings] = useState(true);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const load = useCallback(() => api.backupStatus().then(setStatus).catch((e: Error) => toast.error(e.message)), [toast]);
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (phase.kind !== "restoring") return;
    const timer = window.setTimeout(async () => {
      const v = await probeVersion();
      const sawDown = phase.sawDown || v === null;
      if (v !== null && sawDown) { window.location.reload(); return; }
      if (phase.seconds >= 240) { setPhase({ kind: "timeout" }); return; }
      setPhase({ kind: "restoring", seconds: phase.seconds + 2, sawDown });
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [phase]);

  async function create() {
    setBusy(true);
    try { setStatus(await api.createBackup()); toast.success("Full backup created"); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Could not create the backup"); }
    finally { setBusy(false); }
  }

  async function restore() {
    if (!chosen) return;
    setBusy(true); setChosen(null);
    try {
      await api.restoreBackup(chosen.name, restoreSettings);
      setPhase({ kind: "restoring", seconds: 0, sawDown: false });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start the restore"); setBusy(false);
    }
  }

  if (phase.kind === "restoring") return <div className="page"><section className="panel update-progress" role="status">
    <span className="spinner" aria-hidden="true" /><h1>Restoring your data</h1>
    <p>F&amp;M Finance is closing, restoring the selected database and receipts, and starting again. This page will return.</p>
    <ol className="update-steps"><li className="done">Current data saved as a recovery backup</li>
      <li className={phase.sawDown ? "done" : "now"}>Closing the app</li><li className={phase.sawDown ? "now" : ""}>Restoring and checking the app</li></ol>
  </section></div>;
  if (phase.kind === "timeout") return <div className="page"><section className="panel"><h1>Still waiting</h1>
    <p>Start FMFinance.exe yourself. If the selected backup could not start, the app automatically put the data from
      immediately before the restore back.</p><button className="btn btn-primary" onClick={() => window.location.reload()}>Try again</button>
  </section></div>;

  return <div className="page"><header className="page-head"><div><h1>Backups</h1>
    <p className="page-sub">Protect the database, settings and every locally stored receipt.</p></div>
    <button className="btn btn-primary" disabled={busy || !status?.supported} onClick={() => void create()}>
      {busy ? "Working…" : "Back up now"}</button></header>

    {status?.last_result?.status === "ok" && <div className="callout callout-ok">The backup was restored successfully.</div>}
    {status?.last_result?.status === "rolled_back" && <div className="callout callout-error">The selected backup could not
      start, so the data from immediately before the restore was put back. Nothing was lost.</div>}
    {status && !status.supported && <div className="callout callout-warn">{status.reason}</div>}

    <section className="panel"><h2>Where backups are saved</h2><code className="path-code">{status?.folder ?? "…"}</code>
      <p className="muted small">This folder is outside the FMFinance.exe folder. Moving or replacing the EXE does not move
        these backups. The app makes an automatic backup when it starts and when you use Exit app.</p></section>

    <section className="panel flush"><div className="panel-head"><h2>Available backups</h2>
      <span className="muted">{status?.backups.length ?? 0} backup{status?.backups.length === 1 ? "" : "s"}</span></div>
      {!status ? <div className="empty inner"><p>Loading…</p></div> : status.backups.length === 0
        ? <div className="empty inner"><p>No full backups yet.</p></div>
        : <div className="table-wrap"><table className="ledger"><thead><tr><th>Created</th><th>Type</th><th>Version</th>
            <th>Receipts</th><th className="num">Size</th><th></th></tr></thead><tbody>
          {status.backups.map((b) => <tr key={b.name}><td>{b.created_at ? formatDateTime(b.created_at) : b.name}</td>
            <td>{reasonLabel(b.reason)}</td><td>{b.version || "—"}</td><td>{b.receipt_count}</td>
            <td className="num">{fileSize(b.bytes)}</td><td className="row-actions"><button className="btn btn-small"
              disabled={busy} onClick={() => setChosen(b)}>Restore</button></td></tr>)}
        </tbody></table></div>}
    </section>

    <ConfirmDialog open={Boolean(chosen)} title="Restore this backup?" confirmLabel="Restore and restart"
      danger message={chosen ? `This replaces the current data with the backup from ${chosen.created_at || chosen.name}. A recovery backup of the current data is created first.` : ""}
      onCancel={() => setChosen(null)} onConfirm={() => void restore()}>
      <label className="check"><input type="checkbox" checked={restoreSettings}
        onChange={(e) => setRestoreSettings(e.target.checked)} /> Restore app settings too (recommended for email passwords and keys)</label>
    </ConfirmDialog>
  </div>;
}

function reasonLabel(reason: string): string {
  return ({ startup: "Automatic · start", exit: "Automatic · exit", manual: "Manual",
    "before-restore": "Safety copy" } as Record<string, string>)[reason] ?? reason;
}
