import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NO_RULES, knownWords, span, type PasswordRules } from "./passwordRules";
import { fakeService, renderPortal, shown, type Call } from "./test/portal";
import { SETTLE_MS } from "./useSettled";

const YEAR = 365.24219 * 86400;
const RULES: PasswordRules = {
  min_length: 12,
  history: 3,
  strength: { attacker: "identity-thief", label: "an identity thief", rate: 10000, seconds: YEAR, time: "1 year" },
  lines: ["At least 12 characters", "Different from your last 3 passwords", "Hard enough to guess that an identity thief would need at least 1 year"],
};
const STRONG = "marble kestrel saffron lantern";
const NOT_CHANGED = { error: "Your password was not changed. Learn more", link: "Learn more", help: "/parent/password-help#account" };
const SAVED = { message: "Try signing in with your new password. If it does not work, learn more", link: "learn more", help: "/parent/password-help#reset" };
const SIGNED_OUT = { status: 401, body: { error: "Sign in to see this." } };

function account(rules: PasswordRules, password: (call: Call) => { status?: number; body?: unknown } = () => ({ body: { message: "Your password was changed." } })) {
  return fakeService((call) => {
    if (call.path === "/parent/api/account") return { body: { username: "ada", role: "admin", email: "ada@example.net", rules } };
    if (call.path === "/parent/api/account/password") return password(call);
    return undefined;
  });
}

function signedOut(rules: PasswordRules | null, handler: (call: Call) => { status?: number; body?: unknown } | undefined = () => undefined) {
  return fakeService((call) => {
    if (call.path === "/parent/api/password-reset" && call.method === "GET") {
      return rules === null ? { status: 403, body: { error: "closed", closed: true } } : { body: { email: true, lifetime: "60 minutes", rules } };
    }
    return handler(call) ?? SIGNED_OUT;
  });
}

const advice = () => document.getElementById("new-password-rules")!;
// The advice is worked out again only once typing has paused for SETTLE_MS.
const pause = () => act(() => vi.advanceTimersByTimeAsync(SETTLE_MS));

let user: ReturnType<typeof userEvent.setup>;
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
});
afterEach(() => {
  vi.useRealTimers();
});
const statusBar = () => screen.getByRole("status");

describe("the Account page's password rules", () => {
  it("says which rules the new password breaks as it is typed, and nothing when it passes", async () => {
    account(RULES);
    renderPortal("/parent/account");
    const field = await screen.findByLabelText("New password");
    expect(field).toHaveAccessibleDescription("");
    await user.type(field, "short");
    await pause();
    const lines = Array.from(advice().children, (line) => line.textContent);
    expect(lines).toEqual(["Use at least 12 characters. This one has 5.", expect.stringMatching(/^An identity thief could guess this in /)]);
    await user.clear(field);
    await user.type(field, "correct horse");
    await pause();
    expect(advice()).toHaveTextContent(
      /^An identity thief could guess this in about \d+ hours?\. It needs to hold out for 1 year\. Make it longer, such as by adding another word or two\.$/,
    );
    await user.clear(field);
    await user.type(field, STRONG);
    await pause();
    expect(advice()).toBeEmptyDOMElement();
    expect(screen.getByRole("button", { name: "Change password" })).toBeEnabled();
  });

  it("waits for a pause in the typing before changing the advice", async () => {
    account(RULES);
    renderPortal("/parent/account");
    const field = await screen.findByLabelText("New password");
    await user.type(field, "short");
    expect(advice()).toBeEmptyDOMElement();
    await act(() => vi.advanceTimersByTimeAsync(SETTLE_MS - 100));
    await user.type(field, "er");
    await act(() => vi.advanceTimersByTimeAsync(SETTLE_MS - 100));
    // Each keystroke starts the wait again.
    expect(advice()).toBeEmptyDOMElement();
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(advice().firstChild).toHaveTextContent("Use at least 12 characters. This one has 7.");
    await user.type(field, "-ab");
    // The earlier advice stays until the next pause.
    expect(advice().firstChild).toHaveTextContent("This one has 7.");
    await pause();
    expect(advice().firstChild).toHaveTextContent("This one has 10.");
  });

  it("names no rule that is off", async () => {
    account({ ...NO_RULES, min_length: 12, lines: ["At least 12 characters"] });
    renderPortal("/parent/account");
    await user.type(await screen.findByLabelText("New password"), "correct horse");
    await pause();
    expect(advice()).toBeEmptyDOMElement();
    await user.type(screen.getByLabelText("New password"), "{Backspace}{Backspace}");
    await pause();
    expect(advice()).toHaveTextContent("Use at least 12 characters. This one has 11.");
  });

  it("counts the username, the address, and the current password as known words", async () => {
    account({ ...RULES, min_length: null });
    renderPortal("/parent/account");
    const field = await screen.findByLabelText("New password");
    await user.type(field, "ada2026!");
    await pause();
    expect(advice()).toHaveTextContent(/^An identity thief could guess this in/);
    await user.clear(field);
    await user.type(field, "Summer2026!Picnic");
    await pause();
    expect(advice()).toBeEmptyDOMElement();
    await user.type(screen.getByLabelText("Current password"), "Summer2025!Picnic");
    await pause();
    expect(advice()).toHaveTextContent(/^An identity thief could guess this in/);
  });

  it("refuses Save on the page with the same advice, sending nothing and keeping the fields", async () => {
    const calls = account(RULES);
    renderPortal("/parent/account");
    await user.type(await screen.findByLabelText("Current password"), "s3cret-pass");
    await user.type(screen.getByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("New password again"), "short");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(statusBar()).toHaveTextContent(/^Use at least 12 characters\. This one has 5\. An identity thief/);
    expect(calls.filter((call) => call.path === "/parent/api/account/password")).toEqual([]);
    expect(screen.getByLabelText("New password")).toHaveValue("short");
  });

  it("shows the service's refusal with Learn more, which opens the Account section of Password help", async () => {
    const calls = account(RULES, () => ({ status: 400, body: NOT_CHANGED }));
    const { router } = renderPortal("/parent/account");
    await user.type(await screen.findByLabelText("Current password"), "wrong");
    await user.type(screen.getByLabelText("New password"), STRONG);
    await user.type(screen.getByLabelText("New password again"), STRONG);
    await user.click(screen.getByRole("button", { name: "Change password" }));
    const learn = await within(statusBar()).findByRole("link", { name: "Learn more" });
    expect(statusBar()).toHaveTextContent("Your password was not changed. Learn more");
    expect(learn).toHaveAttribute("href", "/parent/password-help#account");
    expect(calls.filter((call) => call.path === "/parent/api/account/password")).toHaveLength(1);
    await user.click(learn);
    expect(await screen.findByRole("heading", { name: "Password help" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/password-help");
    expect(router.state.location.hash).toBe("#account");
  });
});

describe("the Reset password page's password rules", () => {
  it("checks length and strength as the password is typed, with no known words", async () => {
    signedOut(RULES);
    renderPortal("/parent/reset#abc");
    const field = await screen.findByLabelText("New password");
    await user.type(field, "short");
    await pause();
    expect(advice()).toHaveTextContent(/^Use at least 12 characters\. This one has 5\./);
    await user.clear(field);
    // ada is a known word only where the page knows the account.
    await user.type(field, "Ada-Lovelace-1815");
    await pause();
    expect(advice()).toBeEmptyDOMElement();
  });

  it("refuses Save on the page, and otherwise sends it and opens sign-in with Learn more", async () => {
    const calls = signedOut(RULES, (call) => (call.path === "/parent/api/password-reset/save" ? { body: SAVED } : undefined));
    const { router } = renderPortal("/parent/reset#abc");
    await user.type(await screen.findByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("New password again"), "short");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/^Use at least 12 characters\. This one has 5\./);
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);
    await user.clear(screen.getByLabelText("New password"));
    await user.clear(screen.getByLabelText("New password again"));
    await user.type(screen.getByLabelText("New password"), STRONG);
    await user.type(screen.getByLabelText("New password again"), STRONG);
    await user.click(screen.getByRole("button", { name: "Save" }));
    const notice = await screen.findByRole("status");
    expect(shown(router)).toBe("/parent/login");
    expect(notice).toHaveTextContent("Try signing in with your new password. If it does not work, learn more");
    expect(within(notice).getByRole("link", { name: "learn more" })).toHaveAttribute("href", "/parent/password-help#reset");
  });
});

describe("the Password help page", () => {
  it("works with no session and lists the rules that are on", async () => {
    signedOut(RULES);
    renderPortal("/parent/password-help#reset");
    expect(await screen.findByRole("heading", { name: "Password help" })).toBeInTheDocument();
    expect(document.getElementById("account")).toHaveTextContent(
      "Your password was not changed. Either the current password was wrong, or the new password does not meet this household's password rules.",
    );
    expect(document.getElementById("reset")).toHaveTextContent("Open your link again to try another password, or ask for a new link with Forgot password.");
    for (const section of ["account", "reset"]) {
      expect(document.getElementById(section)).toHaveTextContent("A longer password, such as one with another word or two, usually passes.");
    }
    const rules = within(screen.getByRole("region", { name: "This household's password rules" })).getAllByRole("listitem");
    expect(rules.map((item) => item.textContent)).toEqual(RULES.lines);
    expect(screen.getByRole("link", { name: "Back to the Account page" })).toHaveAttribute("href", "/parent/account");
  });

  it("says when no rule is on, and shows the closed message with no parent account", async () => {
    signedOut(NO_RULES);
    const { unmount } = renderPortal("/parent/password-help");
    expect(await screen.findByText("No password rules are turned on. A password is 1 to 200 characters.")).toBeInTheDocument();
    unmount();
    signedOut(null);
    renderPortal("/parent/password-help");
    expect(await screen.findByText("The parent portal is closed until a parent account is added.")).toBeInTheDocument();
  });
});

describe("the words the service uses too", () => {
  it("makes the same known words as the service", () => {
    expect(knownWords("Ada", "ada.lovelace@example.net", "Summer2025!Picnic")).toEqual([
      "ada",
      "ada.lovelace@example.net",
      "lovelace",
      "example",
      "net",
      "summer2025!picnic",
      "summer",
      "2025",
      "picnic",
    ]);
  });

  it("says a time roughly as the service does", () => {
    expect([0.4, 1, 59.4, 90, 3 * 86400 + 3600, YEAR * 1.4, YEAR * 12345, YEAR * 2e6].map(span)).toEqual([
      "less than a second",
      "about 1 second",
      "about 59 seconds",
      "about 2 minutes",
      "about 3 days",
      "about 1 year",
      "about 12,345 years",
      "more than a million years",
    ]);
  });
});
