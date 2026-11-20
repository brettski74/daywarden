import { KeyRound } from "lucide-react";
import { useState } from "react";
import { Form, useActionData, useLoaderData, useNavigation, type ActionFunctionArgs, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { ContextBar, StatusBar, useTitle } from "../slots";

export const ACCOUNT = "/account";
export const NO_ADDRESS = "No email address. Ask whoever runs Daywarden to add one with dw-account.";

type AccountInfo = { username: string; role: string; email: string | null };
type ChangeResult = { ok: boolean; message: string };

export async function accountLoader({ request }: LoaderFunctionArgs): Promise<AccountInfo> {
  return api<AccountInfo>("/account", { page: pageOf(request), signal: request.signal });
}

/** Change password. The service checks the current password as a sign-in does, and keeps this tab signed in. */
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
    if (error instanceof ApiError) return { ok: false, message: error.message };
    throw error;
  }
}

/**
 * The signed-in account: its username, role, and address, which only the
 * host changes, and Change password. Open to admins and reviewers alike.
 */
export function Account() {
  const account = useLoaderData() as AccountInfo;
  const result = useActionData() as ChangeResult | undefined;
  const navigation = useNavigation();
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
      <Form method="post" className="account-form" key={answers.count} aria-labelledby="change-heading">
        <label htmlFor="current-password">Current password</label>
        <input id="current-password" name="current" type="password" autoComplete="current-password" />
        <label htmlFor="new-password">New password</label>
        <input id="new-password" name="password" type="password" autoComplete="new-password" />
        <label htmlFor="new-password-again">New password again</label>
        <input id="new-password-again" name="again" type="password" autoComplete="new-password" />
        <div>
          <button type="submit" className="button" disabled={navigation.state === "submitting"}>
            <KeyRound aria-hidden="true" />
            Change password
          </button>
        </div>
      </Form>
      <StatusBar>{result && <span className={result.ok ? "status-done" : "status-refused"}>{result.message}</span>}</StatusBar>
    </>
  );
}
