import { Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLoaderData, type LoaderFunctionArgs } from "react-router";
import { openPost, resetSetting, type ResetSetting } from "../api";
import { useTitle } from "../slots";
import { ClosedPortal, SignInPanel } from "./Login";

export const NOT_SET_UP = "Resetting a password by email is not set up. Ask whoever runs Daywarden.";

export async function forgotLoader({ request }: LoaderFunctionArgs): Promise<ResetSetting> {
  return resetSetting(request.signal);
}

/**
 * Forgot password: a username and Send link, with no session. The answer is
 * the same whatever the username, so it says nothing about any account.
 */
export function Forgot() {
  const setting = useLoaderData() as ResetSetting;
  const [username, setUsername] = useState("");
  const [answer, setAnswer] = useState<{ ok: boolean; message: string } | null>(null);
  const [closed, setClosed] = useState(setting === "closed");
  const [busy, setBusy] = useState(false);
  useTitle("Forgot password");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const result = await openPost("/password-reset", { username });
    setBusy(false);
    if (result.closed) setClosed(true);
    setAnswer(result);
  }

  if (closed) {
    return (
      <SignInPanel>
        <ClosedPortal />
      </SignInPanel>
    );
  }
  return (
    <SignInPanel>
      {setting !== "closed" && !setting.email ? (
        <>
          <h1>Forgot password</h1>
          <p>{NOT_SET_UP}</p>
        </>
      ) : (
        <form className="signin-form" onSubmit={submit} aria-labelledby="forgot-heading">
          <h1 id="forgot-heading">Forgot password</h1>
          <p className="signin-hint">Enter your username, and a link to choose a new password will be sent to the account's email address.</p>
          <label htmlFor="username">Username</label>
          <input id="username" autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} />
          {answer && (
            <p className={answer.ok ? "signin-notice" : "signin-failure"} role={answer.ok ? "status" : "alert"}>
              {answer.message}
            </p>
          )}
          <div className="signin-buttons">
            <button type="submit" className="button" disabled={busy}>
              <Send aria-hidden="true" />
              Send link
            </button>
          </div>
        </form>
      )}
      <p className="signin-link">
        <Link to="/login">Back to sign in</Link>
      </p>
    </SignInPanel>
  );
}
