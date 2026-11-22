import { Save } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs } from "react-router";
import { openPost, resetSetting, type ResetSetting } from "../api";
import { RuleAdvice } from "../components/RuleAdvice";
import { loadEstimate, ruleProblems, type Estimate } from "../passwordRules";
import { useTitle } from "../slots";
import { useSettled } from "../useSettled";
import { ClosedPortal, SignInPanel, type LoginState } from "./Login";

type Loaded = { setting: ResetSetting; estimate: Estimate | null };

export async function resetLoader({ request }: LoaderFunctionArgs): Promise<Loaded> {
  const setting = await resetSetting(request.signal);
  return { setting, estimate: setting === "closed" ? null : await loadEstimate(setting.rules) };
}

/**
 * Reset password: the page every emailed link opens, valid or not. It shows
 * nothing about the account or the link. The token is the address's fragment,
 * which a browser never sends to a server. It is read only on Save and sent
 * in the body of the POST.
 *
 * It checks the household's length and strength rules as the parent types
 * (S046). It knows no username, address, or current password, so it uses no
 * known words. Once a password is sent, the answer is the same whatever the
 * service did with it.
 */
export function Reset() {
  const { setting, estimate } = useLoaderData() as Loaded;
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [closed, setClosed] = useState(setting === "closed");
  const [busy, setBusy] = useState(false);
  useTitle("Choose a new password");
  const check = (password: string) => (setting === "closed" ? [] : ruleProblems(password, setting.rules, estimate, []));
  // The advice follows the field once typing pauses, not on every keystroke.
  const settled = useSettled(password);
  const advice = useMemo(() => (settled === "" ? [] : check(settled)), [settled, setting, estimate]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problems = check(password);
    if (problems.length) {
      setFailure(problems.join(" "));
      return;
    }
    setBusy(true);
    const token = hash.replace(/^#/, "");
    const result = await openPost("/password-reset/save", { token, password, again });
    setBusy(false);
    if (result.ok) {
      const state: LoginState = { notice: result.message, link: result.link, help: result.help };
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
            aria-describedby="new-password-rules"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setFailure(null);
            }}
          />
          <RuleAdvice id="new-password-rules" problems={password === "" ? [] : advice} />
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
