import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderPortal, shown } from "./test/portal";

const SIGNED_OUT = { status: 401, body: { error: "Sign in to see this." } };

describe("the sign-in screen", () => {
  it("is plain: the logo, the two fields, and Login and Reset, with no sidebar or bars", async () => {
    fakeService((call) => (call.path === "/parent/api/session" ? SIGNED_OUT : undefined));
    renderPortal("/parent/login");
    expect(await screen.findByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Daywarden" })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveFocus();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Portal pages" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("opens the page that was asked for after the right password, entered with Enter", async () => {
    let signedIn = false;
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/login") {
        signedIn = true;
        return { body: { next: "/parent/attempts?client=younger" } };
      }
      return signedIn ? undefined : SIGNED_OUT;
    });
    const { router } = renderPortal("/parent/login?next=%2Fparent%2Fattempts%3Fclient%3Dyounger");
    await userEvent.type(await screen.findByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "s3cret-pass{Enter}");
    expect(await screen.findByRole("link", { name: "spelling-week-3" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/attempts?client=younger");
    const login = calls.find((call) => call.path === "/parent/api/login");
    expect(login).toEqual({
      path: "/parent/api/login",
      search: "",
      method: "POST",
      body: { username: "ada", password: "s3cret-pass", next: "/parent/attempts?client=younger" },
    });
  });

  it("opens the portal home when the service answers with a return address that is not a page", async () => {
    let signedIn = false;
    fakeService((call) => {
      if (call.path === "/parent/api/login") {
        signedIn = true;
        return { body: { next: "/parent/api/attempts" } };
      }
      return signedIn ? undefined : SIGNED_OUT;
    });
    const { router } = renderPortal("/parent/login?next=%2Fparent%2Fapi%2Fattempts");
    await userEvent.type(await screen.findByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "s3cret-pass");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    await screen.findByText("Choose a client group.");
    expect(shown(router)).toBe("/parent/attempts");
  });

  it("stays on the screen with the failure after a wrong password", async () => {
    fakeService((call) =>
      call.path === "/parent/api/login" ? { status: 401, body: { error: "Username or password incorrect." } } : SIGNED_OUT,
    );
    const { router } = renderPortal("/parent/login");
    await userEvent.type(await screen.findByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "wrong{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Username or password incorrect.");
    expect(router.state.location.pathname).toBe("/parent/login");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("Reset clears both fields and the failure and puts the cursor in Username", async () => {
    fakeService((call) =>
      call.path === "/parent/api/login" ? { status: 401, body: { error: "Username or password incorrect." } } : SIGNED_OUT,
    );
    const { router } = renderPortal("/parent/login?next=%2Fparent%2Fusage");
    await userEvent.type(await screen.findByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "wrong{Enter}");
    await screen.findByRole("alert");
    await userEvent.type(screen.getByLabelText("Password"), "half-typed");
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveFocus();
    expect(shown(router)).toBe("/parent/login?next=%2Fparent%2Fusage");
  });

  it("says the portal is closed and shows no fields when there is no parent account", async () => {
    fakeService(() => ({ status: 403, body: { error: "The parent portal is closed until a parent account is added.", closed: true } }));
    const { router } = renderPortal("/parent/attempts?client=younger");
    expect(await screen.findByText("The parent portal is closed until a parent account is added.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/parent/login");
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("opens the portal home when the parent is already signed in", async () => {
    fakeService();
    const { router } = renderPortal("/parent/login");
    await screen.findByText("Choose a client group.");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts"));
  });
});
