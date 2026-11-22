import { KeyRound } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Form, useActionData, useLoaderData, useNavigation, type ActionFunctionArgs, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { HelpMessage, type Helped } from "../components/HelpMessage";
import { NO_RULES, knownWords, loadEstimate, ruleProblems, type Estimate, type PasswordRules } from "../passwordRules";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { RuleAdvice } from "../components/RuleAdvice";
import { useSettled } from "../useSettled";

export const ACCOUNT = "/account";
export const NO_ADDRESS = "No email address. Ask whoever runs Daywarden to add one with dw-account.";

type AccountInfo = { username: string; role: string; email: string | null; rules: PasswordRules };
type Loaded = AccountInfo & { estimate: Estimate | null };
type ChangeResult = Helped & { ok: boolean };

export async function accountLoader({ request }: LoaderFunctionArgs): Promise<Loaded> {
  const account = await api<AccountInfo>("/account", { page: pageOf(request), signal: request.signal });
  const rules = account.rules ?? NO_RULES;
  return { ...account, rules, estimate: await loadEstimate(rules) };
}

/** Change password. The service checks the current password as a sign-in does, checks the rules again, and keeps this tab signed in. */
export async function accountAction({ request }: ActionFunctionArgs): Promise<ChangeResult> {
  const form = await request.formData();
  try {
    const done = await api<{ message: string }>("/account/password", {
      page: pageOf(request),
      method: "POST",
      body: { current: form.get("current"), password: form.get("password"), again: form.get("again") },
    });
    return { ok: true, message: done.message };
  } catch (error) {
    if (error instanceof ApiError) {
      const { link, help } = error.data as { link?: string; help?: string };
      return { ok: false, message: error.message, link, help };
    }
    throw error;
  }
}

/**
 * The signed-in account: its username, role, and address, which only the
 * host changes, and Change password. Open to admins and reviewers alike.
 */
export function Account() {
  const account = useLoaderData() as Loaded;
  const result = useActionData() as ChangeResult | undefined;
  // Each answer starts a fresh form, so no password is left in the fields.
  const [answers, setAnswers] = useState<{ held?: ChangeResult; count: number }>({ count: 0 });
  if (result !== answers.held) setAnswers({ held: result, count: answers.count + 1 });
  useTitle("Account");

  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Account</h1>
      </ContextBar>
      <dl className="summary">
        <div>
          <dt>Username</dt>
          <dd>{account.username}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{account.role}</dd>
        </div>
        <div>
          <dt>Email address</dt>
          <dd>{account.email ?? NO_ADDRESS}</dd>
        </div>
      </dl>
      <h2 id="change-heading">Change password</h2>
      <ChangeForm key={answers.count} account={account} result={result} />
    </>
  );
}

/** The three fields, the rules the new password breaks as it is typed, and the status bar's answer. */
function ChangeForm({ account, result }: { account: Loaded; result: ChangeResult | undefined }) {
  const navigation = useNavigation();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [refused, setRefused] = useState<string[] | null>(null);
  const check = (password: string, current: string) =>
    ruleProblems(password, account.rules, account.estimate, knownWords(account.username, account.email, current));
  // The advice follows the fields once typing pauses, not on every keystroke.
  const settledPassword = useSettled(password);
  const settledCurrent = useSettled(current);
  const advice = useMemo(
    () => (settledPassword === "" ? [] : check(settledPassword, settledCurrent)),
    [settledPassword, settledCurrent, account],
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    // A password that breaks length or strength is refused here, and nothing is sent.
    const problems = check(password, current);
    if (problems.length) {
      event.preventDefault();
      setRefused(problems);
    }
  }

  const status = refused ? (
    <span className="status-refused">{refused.join(" ")}</span>
  ) : (
    result && (
      <span className={result.ok ? "status-done" : "status-refused"}>
        <HelpMessage {...result} />
      </span>
    )
  );

  return (
    <>
      <Form method="post" className="account-form" aria-labelledby="change-heading" onSubmit={submit}>
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          name="current"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <label htmlFor="new-password">New password</label>
        <input
          id="new-password"
          name="password"
          type="password"
          autoComplete="new-password"
          aria-describedby="new-password-rules"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            setRefused(null);
          }}
        />
        <RuleAdvice id="new-password-rules" problems={password === "" ? [] : advice} />
        <label htmlFor="new-password-again">New password again</label>
        <input id="new-password-again" name="again" type="password" autoComplete="new-password" />
        <div>
          <button type="submit" className="button" disabled={navigation.state === "submitting"}>
            <KeyRound aria-hidden="true" />
            Change password
          </button>
        </div>
      </Form>
      <StatusBar>{status}</StatusBar>
    </>
  );
}
