import { useEffect } from "react";
import { Link, useLoaderData, useLocation, type LoaderFunctionArgs } from "react-router";
import { resetSetting, type ResetSetting } from "../api";
import { useTitle } from "../slots";
import { ClosedPortal, SignInPanel } from "./Login";

export async function passwordHelpLoader({ request }: LoaderFunctionArgs): Promise<ResetSetting> {
  return resetSetting(request.signal);
}

const ADVICE =
  "A password used recently, or one close to the username or email address, is refused. " +
  "A longer password, such as one with another word or two, usually passes.";

/**
 * Password help (S046): why the service may not have changed a password, in
 * general terms. It needs no session, and every visitor sees the same page:
 * the rules it lists come from the settings, not from any account. The
 * Account page's Learn more opens #account, and the sign-in screen's after a
 * reset opens #reset.
 */
export function PasswordHelp() {
  const setting = useLoaderData() as ResetSetting;
  const { hash } = useLocation();
  useTitle("Password help");

  useEffect(() => {
    // A link from another portal page changes the address without the browser's own jump to the section.
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [hash]);

  if (setting === "closed") {
    return (
      <SignInPanel>
        <ClosedPortal />
      </SignInPanel>
    );
  }
  const lines = setting.rules.lines;
  return (
    <SignInPanel wide>
      <div className="help-page">
        <h1>Password help</h1>
        <section id="account" aria-labelledby="account-heading">
          <h2 id="account-heading">Changing your password on the Account page</h2>
          <p>
            Your password was not changed. Either the current password was wrong, or the new password does not meet this
            household's password rules.
          </p>
          <p>{ADVICE}</p>
        </section>
        <section id="reset" aria-labelledby="reset-heading">
          <h2 id="reset-heading">Choosing a password from a reset link</h2>
          <p>
            If your link was still valid and your new password meets this household's password rules, it is saved. If you
            cannot sign in with it, either the link had stopped working or the password was refused. Open your link again to
            try another password, or ask for a new link with Forgot password.
          </p>
          <p>{ADVICE}</p>
        </section>
        <section aria-labelledby="rules-heading">
          <h2 id="rules-heading">This household's password rules</h2>
          {lines.length ? (
            <ul>
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p>No password rules are turned on. A password is 1 to 200 characters.</p>
          )}
        </section>
        <p className="signin-link">
          <Link to="/account">Back to the Account page</Link>
        </p>
      </div>
    </SignInPanel>
  );
}
