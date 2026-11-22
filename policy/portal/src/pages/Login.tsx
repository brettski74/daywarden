import { LogIn, RotateCcw } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, redirect, useLoaderData, useLocation, useNavigate, useSearchParams, type LoaderFunctionArgs } from "react-router";
import { HOME_ROUTE, currentSession, resetSetting, signIn, withinPortal } from "../api";
import { HelpMessage } from "../components/HelpMessage";
import { useTitle } from "../slots";

type Loaded = { closed: boolean; forgot: boolean };

/** What another page sends the sign-in screen to say, such as the Reset password page's answer, with its help link. */
export type LoginState = { notice?: string; link?: string; help?: string } | null;

export async function loginLoader({ request }: LoaderFunctionArgs): Promise<Loaded> {
  const session = await currentSession(request.signal);
  if (typeof session === "object") throw redirect(HOME_ROUTE);
  if (session === "closed") return { closed: true, forgot: false };
  const reset = await resetSetting(request.signal);
  return { closed: reset === "closed", forgot: reset !== "closed" && reset.email };
}

/** What the sign-in, Forgot password, and Reset password screens show when there is no parent account. */
export function ClosedPortal() {
  return (
    <>
      <h1>Parent portal</h1>
      <p>The parent portal is closed until a parent account is added.</p>
      <p>Add one on the server with dw-account add --role admin --password USERNAME.</p>
    </>
  );
}

/** The panel the sign-in, Forgot password, and Reset password screens share: the logo and what is beneath it. */
export function SignInPanel({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="signin">
      <div className={wide ? "signin-panel signin-panel-wide" : "signin-panel"}>
        <div className="signin-logo" role="img" aria-label="Daywarden" />
        {children}
      </div>
    </div>
  );
}

/** The plain sign-in screen: the logo, the two fields, and Login and Reset. No sidebar or bars. */
export function Login() {
  const loaded = useLoaderData() as Loaded;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const sent = useLocation().state as LoginState;
  const notice = sent?.notice;
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
    <SignInPanel>
        {closed ? (
          <ClosedPortal />
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
            {notice && !failure && (
              <p className="signin-notice" role="status">
                <HelpMessage message={notice} link={sent?.link} help={sent?.help} />
              </p>
            )}
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
            {loaded.forgot && (
              <p className="signin-link">
                <Link to="/forgot">Forgot password</Link>
              </p>
            )}
          </form>
        )}
    </SignInPanel>
  );
}
