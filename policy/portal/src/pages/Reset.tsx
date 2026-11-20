import { Save } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs } from "react-router";
import { openPost, resetSetting, type ResetSetting } from "../api";
import { useTitle } from "../slots";
import { ClosedPortal, SignInPanel, type LoginState } from "./Login";

export async function resetLoader({ request }: LoaderFunctionArgs): Promise<ResetSetting> {
  return resetSetting(request.signal);
}

/**
 * Reset password: the page every emailed link opens, valid or not. It shows
 * nothing about the account or the link. The token is the address's fragment,
 * which a browser never sends to a server. It is read only on Save and sent
 * in the body of the POST.
 */
export function Reset() {
  const setting = useLoaderData() as ResetSetting;
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [closed, setClosed] = useState(setting === "closed");
  const [busy, setBusy] = useState(false);
  useTitle("Choose a new password");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const token = hash.replace(/^#/, "");
    const result = await openPost("/password-reset/save", { token, password, again });
    setBusy(false);
    if (result.ok) {
      const state: LoginState = { notice: result.message };
      navigate("/login", { replace: true, state });
      return;
    }
    if (result.closed) setClosed(true);
    setFailure(result.message);
  }

  return (
    <SignInPanel>
      {closed ? (
        <ClosedPortal />
      ) : (
        <form className="signin-form" onSubmit={submit} aria-labelledby="reset-heading">
          <h1 id="reset-heading">Choose a new password</h1>
          <label htmlFor="new-password">New password</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            autoFocus
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label htmlFor="new-password-again">New password again</label>
          <input
            id="new-password-again"
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={(event) => setAgain(event.target.value)}
          />
          {failure && (
            <p className="signin-failure" role="alert">
              {failure}
            </p>
          )}
          <div className="signin-buttons">
            <button type="submit" className="button" disabled={busy}>
              <Save aria-hidden="true" />
              Save
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
