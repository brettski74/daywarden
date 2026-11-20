import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderPortal, shown, type Call } from "./test/portal";

const SIGNED_OUT = { status: 401, body: { error: "Sign in to see this." } };
const CLOSED = { status: 403, body: { error: "The parent portal is closed until a parent account is added.", closed: true } };
const EMAIL_ON = { body: { email: true, lifetime: "60 minutes" } };
const EMAIL_OFF = { body: { email: false, lifetime: "60 minutes" } };
const SENT = "If that account has an email address, a link to reset its password is on its way. It works for 60 minutes.";
const SAVED = "If your link was still valid, your new password is saved. If you cannot sign in with it, ask for a new link with Forgot password.";

/** A signed-out browser, with resetting by email on or off. */
function signedOut(reset: { body: unknown } | { status: number; body: unknown }, handler: (call: Call) => { status?: number; body?: unknown } | undefined = () => undefined) {
  return fakeService((call) => {
    if (call.path === "/parent/api/password-reset" && call.method === "GET") return reset;
    return handler(call) ?? SIGNED_OUT;
  });
}

describe("the sign-in screen's Forgot password link", () => {
  it("is there with email on and goes to the Forgot password page", async () => {
    signedOut(EMAIL_ON);
    const { router } = renderPortal("/parent/login");
    await userEvent.click(await screen.findByRole("link", { name: "Forgot password" }));
    expect(await screen.findByRole("heading", { name: "Forgot password" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/forgot");
  });

  it("is not there with email off", async () => {
    signedOut(EMAIL_OFF);
    renderPortal("/parent/login");
    await screen.findByRole("button", { name: "Login" });
    expect(screen.queryByRole("link", { name: "Forgot password" })).not.toBeInTheDocument();
  });
});

describe("the Forgot password page", () => {
  it("sends the username and shows the answer, which is the same for every username", async () => {
    const calls = signedOut(EMAIL_ON, (call) => (call.path === "/parent/api/password-reset" ? { body: { message: SENT } } : undefined));
    renderPortal("/parent/forgot");
    await userEvent.type(await screen.findByLabelText("Username"), "nana");
    await userEvent.click(screen.getByRole("button", { name: "Send link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(SENT);
    expect(calls.filter((call) => call.method === "POST")).toEqual([{ path: "/parent/api/password-reset", search: "", method: "POST", body: { username: "nana" } }]);
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/parent/login");
  });

  it("says resetting is not set up with email off, and has no form", async () => {
    signedOut(EMAIL_OFF);
    renderPortal("/parent/forgot");
    expect(await screen.findByText("Resetting a password by email is not set up. Ask whoever runs Daywarden.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });

  it("shows the closed portal message with no parent account", async () => {
    fakeService(() => CLOSED);
    renderPortal("/parent/forgot");
    expect(await screen.findByText("The parent portal is closed until a parent account is added.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });
});

describe("the Reset password page", () => {
  it("shows only the two fields and Save, sends the token from the fragment, and opens sign-in with the answer", async () => {
    const token = "ab".repeat(32);
    const calls = signedOut(EMAIL_ON, (call) => (call.path === "/parent/api/password-reset/save" ? { body: { message: SAVED } } : undefined));
    const { router } = renderPortal(`/parent/reset#${token}`);
    expect(await screen.findByRole("heading", { name: "Choose a new password" })).toBeInTheDocument();
    // Opening the page sends nothing about the link.
    expect(calls.some((call) => JSON.stringify(call).includes(token))).toBe(false);
    await userEvent.type(screen.getByLabelText("New password"), "garden-gate-7");
    await userEvent.type(screen.getByLabelText("New password again"), "garden-gate-7");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent(SAVED);
    expect(shown(router)).toBe("/parent/login");
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
    const saved = calls.find((call) => call.path === "/parent/api/password-reset/save");
    expect(saved).toEqual({ path: "/parent/api/password-reset/save", search: "", method: "POST", body: { token, password: "garden-gate-7", again: "garden-gate-7" } });
  });

  it("keeps the page with the reason when the password is refused", async () => {
    signedOut(EMAIL_ON, (call) => (call.path === "/parent/api/password-reset/save" ? { status: 400, body: { error: "The two new passwords differ." } } : undefined));
    const { router } = renderPortal("/parent/reset#abc");
    await userEvent.type(await screen.findByLabelText("New password"), "one");
    await userEvent.type(screen.getByLabelText("New password again"), "two");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The two new passwords differ.");
    expect(router.state.location.pathname).toBe("/parent/reset");
  });
});

describe("the Account page", () => {
  const sidebar = () => screen.getByRole("complementary", { name: "Portal" });

  it("is linked from the signed-in line and shows the account with Change password", async () => {
    fakeService((call) => (call.path === "/parent/api/account" ? { body: { username: "ada", role: "admin", email: "ada@example.net" } } : undefined));
    const { router } = renderPortal("/parent/attempts");
    await screen.findByRole("complementary", { name: "Portal" });
    await userEvent.click(within(sidebar()).getByRole("link", { name: "Signed in as ada (admin)" }));
    expect(await screen.findByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/account");
    expect(screen.getByText("ada@example.net")).toBeInTheDocument();
    expect(screen.getByText("admin", { selector: "dd" })).toBeInTheDocument();
    // Nothing but the password can be changed: there is no text box, only the three password fields.
    expect(screen.queryAllByRole("textbox")).toEqual([]);
    expect(screen.getByLabelText("Current password")).toHaveAttribute("type", "password");
  });

  it("says how to get an address when the account has none", async () => {
    fakeService((call) => (call.path === "/parent/api/account" ? { body: { username: "bee", role: "admin", email: null } } : undefined));
    renderPortal("/parent/account");
    expect(await screen.findByText("No email address. Ask whoever runs Daywarden to add one with dw-account.")).toBeInTheDocument();
  });

  it("sends the three passwords and says the answer in the status bar, clearing the fields", async () => {
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/account") return { body: { username: "nana", role: "reviewer", email: "nana@example.net" } };
      if (call.path === "/parent/api/session") return { body: { username: "nana", role: "reviewer" } };
      if (call.path === "/parent/api/account/password") {
        const sent = call.body as { current: string };
        return sent.current === "right" ? { body: { message: "Your password was changed." } } : { status: 400, body: { error: "The current password is wrong. Nothing was changed." } };
      }
      return undefined;
    });
    renderPortal("/parent/account");
    const fill = async (current: string) => {
      await userEvent.type(await screen.findByLabelText("Current password"), current);
      await userEvent.type(screen.getByLabelText("New password"), "new-pass-1");
      await userEvent.type(screen.getByLabelText("New password again"), "new-pass-1");
      await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    };
    await fill("wrong");
    expect(await screen.findByText("The current password is wrong. Nothing was changed.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Current password")).toHaveValue(""));
    await fill("right");
    expect(await screen.findByText("Your password was changed.")).toBeInTheDocument();
    const posted = calls.filter((call) => call.path === "/parent/api/account/password");
    expect(posted.at(-1)?.body).toEqual({ current: "right", password: "new-pass-1", again: "new-pass-1" });
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });
});
