import { useState } from "react";

/** Shows a new user's temporary password once, with a copy button. */
export default function TempPassword({ email, password, onDone }: { email: string; password: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="callout callout-ok temp-pw" role="status">
      <strong>New sign-in created for {email}</strong>
      <p>Temporary password: <code>{password}</code>{" "}
        <button type="button" className="link-button" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button></p>
      <p className="hint">Share it privately (not in the same email as the address). This is the only time it's shown;
        they should change it in Settings after signing in.</p>
      <div><button type="button" className="btn btn-small" onClick={onDone}>Done</button></div>
    </div>
  );
}
