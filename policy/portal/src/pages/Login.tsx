import { LogIn, RotateCcw } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { redirect, useLoaderData, useNavigate, useSearchParams, type LoaderFunctionArgs } from "react-router";
import { HOME_ROUTE, currentSession, signIn, withinPortal } from "../api";
import { useTitle } from "../slots";

type Loaded = { closed: boolean };

export async function loginLoader({ request }: LoaderFunctionArgs): Promise<Loaded> {
  const session = await currentSession(request.signal);
  if (typeof session === "object") throw redirect(HOME_ROUTE);
  return { closed: session === "closed" };
}

/** The plain sign-in screen: the logo, the two fields, and Login and Reset. No sidebar or bars. */
export function Login() {
  const loaded = useLoaderData() as Loaded;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const usernameField = useRef<HTMLInputElement>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [closed, setClosed] = useState(loaded.closed);
  const [busy, setBusy] = useState(false);
  useTitle("Sign in");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const result = await signIn(username, password, searchParams.get("next"));
    setBusy(false);
    if ("next" in result) {
      navigate(withinPortal(result.next), { replace: true });
      return;
    }
    if (result.closed) setClosed(true);
    setFailure(result.error);
    setPassword("");
  }

  function reset() {
    setUsername("");
    setPassword("");
    setFailure(null);
    usernameField.current?.focus();
  }

  return (
    <div className="signin">
      <div className="signin-panel">
        <div className="signin-logo" role="img" aria-label="Daywarden" />
        {closed ? (
          <>
            <h1>Parent portal</h1>
            <p>The parent portal is closed until a parent account is added.</p>
            <p>Add one on the server with the add-parent command.</p>
          </>
        ) : (
          <form className="signin-form" onSubmit={submit} onReset={reset} aria-labelledby="signin-heading">
            <h1 id="signin-heading">Sign in</h1>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              ref={usernameField}
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {failure && (
              <p className="signin-failure" role="alert">
                {failure}
              </p>
            )}
            <div className="signin-buttons">
              <button type="submit" className="button" disabled={busy}>
                <LogIn aria-hidden="true" />
                Login
              </button>
              <button type="reset" className="button button-quiet">
                <RotateCcw aria-hidden="true" />
                Reset
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
