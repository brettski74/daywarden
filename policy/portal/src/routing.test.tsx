import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ATTEMPTS, fakeService, renderPortal, shown } from "./test/portal";

describe("each portal address opens its page", () => {
  it("opens the attempts for the group in the address", async () => {
    const calls = fakeService();
    renderPortal("/parent/attempts?client=younger");
    expect(await screen.findByRole("link", { name: "spelling-week-3" })).toHaveAttribute("href", "/parent/attempts/42");
    expect(screen.getByRole("combobox", { name: "Client group" })).toHaveValue("younger");
    expect(screen.getByText("Today's score")).toBeInTheDocument();
    expect(calls.map((call) => call.path + call.search)).toContain("/parent/api/attempts?client=younger");
    expect(screen.getByRole("status")).toHaveTextContent("1 attempt listed.");
    expect(screen.getByRole("status")).toHaveTextContent("Times are Australia/Sydney.");
    expect(document.title).toBe("Attempts · Daywarden");
  });

  it("opens attempts at the portal home", async () => {
    fakeService();
    const { router } = renderPortal("/parent/");
    expect(await screen.findByText("Choose a client group.")).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/attempts");
  });

  it("opens one attempt with links back to the list and the group", async () => {
    fakeService();
    renderPortal("/parent/attempts/42");
    const crumbs = await screen.findByRole("navigation", { name: "Where you are" });
    expect(within(crumbs).getByRole("link", { name: "Attempts" })).toHaveAttribute("href", "/parent/attempts");
    expect(within(crumbs).getByRole("link", { name: "younger" })).toHaveAttribute("href", "/parent/attempts?client=younger");
    expect(within(crumbs).getByRole("heading", { name: "spelling-week-3" })).toBeInTheDocument();
    expect(screen.getByText("Given up and carried on")).toBeInTheDocument();
    expect(screen.getByText("wombat")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("settings")).toBeInTheDocument();
  });

  it("says an attempt number that is not stored is not stored, inside the layout", async () => {
    fakeService((call) => (call.path === "/parent/api/attempts/999999" ? { status: 404, body: { error: "That attempt is not stored." } } : undefined));
    renderPortal("/parent/attempts/999999");
    expect(await screen.findByText("That attempt is not stored.")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Portal pages" })).toBeInTheDocument();
  });

  it("opens the usage report the address asks for", async () => {
    const calls = fakeService((call) =>
      call.path === "/parent/api/usage"
        ? {
            body: {
              times: "Times are Australia/Sydney.",
              choices: { clients: ["younger", "default"], sites: ["default"], quotas: ["youtube"] },
              chosen: { view: "quota", client: "", site: "", quota: "youtube" },
              report: { kind: "balances", heading: "youtube", day: "Sunday 8 November 2026", limits: ["Time limit: 2h.", "Byte limit: 1 KB."], rows: [], empty: "No client group has a balance." },
              message: null,
            },
          }
        : undefined,
    );
    renderPortal("/parent/usage?view=quota&quota=youtube");
    expect(await screen.findByText("No client group has a balance.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Show" })).toHaveValue("quota");
    expect(screen.getByRole("combobox", { name: "Quota" })).toHaveValue("youtube");
    expect(calls.map((call) => call.path + call.search)).toContain("/parent/api/usage?view=quota&quota=youtube");
  });

  it("shows a not-found message for an unknown address with the layout around it", async () => {
    fakeService();
    renderPortal("/parent/nothing-here");
    expect(await screen.findByText("There is no portal page at this address.")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Portal pages" })).toBeInTheDocument();
  });
});

describe("the sidebar", () => {
  it("lists every page as a real link and marks the open one", async () => {
    fakeService();
    renderPortal("/parent/usage");
    const nav = await screen.findByRole("navigation", { name: "Portal pages" });
    const attempts = within(nav).getByRole("link", { name: "Attempts" });
    const usage = within(nav).getByRole("link", { name: "Usage" });
    expect(attempts.tagName).toBe("A");
    expect(attempts).toHaveAttribute("href", "/parent/attempts");
    expect(usage).toHaveAttribute("href", "/parent/usage");
    expect(usage).toHaveAttribute("aria-current", "page");
    expect(attempts).not.toHaveAttribute("aria-current");
    expect(screen.getByText("ada")).toBeInTheDocument();
  });

  it("changes page in place when an entry is clicked", async () => {
    fakeService();
    const { router } = renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    await userEvent.click(screen.getByRole("link", { name: "Usage" }));
    expect(await screen.findByText("Choose a site group, a client group, or a quota.")).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/usage");
    expect(screen.getByRole("link", { name: "Usage" })).toHaveAttribute("aria-current", "page");
  });

  it("changes page in a browser whose scrollTo returns a promise, as current Chromium's does", async () => {
    const before = Object.getOwnPropertyDescriptor(Element.prototype, "scrollTo");
    Object.defineProperty(Element.prototype, "scrollTo", { configurable: true, value: () => Promise.resolve() });
    try {
      fakeService();
      renderPortal("/parent/attempts?client=younger");
      await screen.findByRole("link", { name: "spelling-week-3" });
      await userEvent.click(screen.getByRole("link", { name: "Usage" }));
      expect(await screen.findByText("Choose a site group, a client group, or a quota.")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("link", { name: "Attempts" }));
      expect(await screen.findByText("Choose a client group.")).toBeInTheDocument();
    } finally {
      if (before) Object.defineProperty(Element.prototype, "scrollTo", before);
      else delete (Element.prototype as { scrollTo?: unknown }).scrollTo;
    }
  });
});

describe("pull-down choices live in the address", () => {
  it("writes the attempts group to the address and Back returns to the one before", async () => {
    const calls = fakeService();
    const { router } = renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Client group" }), "older");
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=older"));
    expect(calls.map((call) => call.path + call.search)).toContain("/parent/api/attempts?client=older");
    await router.navigate(-1);
    await waitFor(() => expect(shown(router)).toBe("/parent/attempts?client=younger"));
  });

  it("writes each usage choice to the address and keeps the others", async () => {
    fakeService();
    const { router } = renderPortal("/parent/usage");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Show" }), "quota");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage?view=quota"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Quota" }), "youtube");
    await waitFor(() => expect(shown(router)).toBe("/parent/usage?view=quota&quota=youtube"));
  });
});

describe("a refused data request returns to its page after sign-in", () => {
  it("sends a loader's 401 to sign-in with the page being opened, not the data address", async () => {
    fakeService(() => ({ status: 401, body: { error: "Sign in to see this." } }));
    const { router } = renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("button", { name: "Login" });
    expect(router.state.location.pathname).toBe("/parent/login");
    expect(new URLSearchParams(router.state.location.search).get("next")).toBe("/parent/attempts?client=younger");
    expect(screen.queryByRole("navigation", { name: "Portal pages" })).not.toBeInTheDocument();
  });

  it("sends a 401 found while moving to another page back to that page", async () => {
    let signedIn = true;
    fakeService(() => (signedIn ? undefined : { status: 401, body: {} }));
    const { router } = renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    signedIn = false;
    await userEvent.click(screen.getByRole("link", { name: "Usage" }));
    await screen.findByRole("button", { name: "Login" });
    expect(new URLSearchParams(router.state.location.search).get("next")).toBe("/parent/usage");
  });

  it("sends an action's 401 back to the page on show and does not repeat the action after sign-in", async () => {
    let signedIn = true;
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/login") {
        signedIn = true;
        return { body: { next: (call.body as { next: string }).next } };
      }
      if (call.path === "/parent/api/parent-check") return { status: 401, body: {} };
      return signedIn ? undefined : { status: 401, body: {} };
    });
    const { router } = renderPortal("/parent/attempts?client=younger");
    await screen.findByRole("link", { name: "spelling-week-3" });
    signedIn = false;
    await userEvent.click(screen.getByRole("button", { name: "Record parent check" }));
    await screen.findByRole("button", { name: "Login" });
    expect(new URLSearchParams(router.state.location.search).get("next")).toBe("/parent/attempts?client=younger");

    await userEvent.type(screen.getByLabelText("Username"), "ada");
    await userEvent.type(screen.getByLabelText("Password"), "s3cret-pass");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(await screen.findByRole("link", { name: "spelling-week-3" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/attempts?client=younger");
    expect(screen.getByRole("navigation", { name: "Portal pages" })).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/parent/api/parent-check")).toHaveLength(1);
  });
});

describe("record parent check", () => {
  it("cannot be used until a group is chosen", async () => {
    fakeService();
    renderPortal("/parent/attempts");
    expect(await screen.findByText("Choose a client group.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record parent check" })).toBeDisabled();
  });

  it("records one pass for the group on show, confirms it, and reloads the list", async () => {
    let recorded = false;
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/parent-check") {
        recorded = true;
        return { body: { message: "Recorded a parent check for younger." } };
      }
      if (call.path === "/parent/api/attempts" && recorded) {
        return {
          body: {
            ...ATTEMPTS,
            attempts: [{ ...ATTEMPTS.attempts[0], id: 43, task: "parent_check", set: "Parent check" }, ...ATTEMPTS.attempts],
          },
        };
      }
      return undefined;
    });
    renderPortal("/parent/attempts?client=younger");
    await userEvent.click(await screen.findByRole("button", { name: "Record parent check" }));
    expect(await screen.findByText("Recorded a parent check for younger.")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "parent_check" })).toBeInTheDocument();
    expect(screen.getByText("Parent check")).toBeInTheDocument();
    const checks = calls.filter((call) => call.path === "/parent/api/parent-check");
    expect(checks).toEqual([{ path: "/parent/api/parent-check", search: "", method: "POST", body: { client: "younger" } }]);
  });
});

describe("sign out", () => {
  it("ends the session on the service and shows the sign-in screen", async () => {
    let signedIn = true;
    const calls = fakeService((call) => {
      if (call.path === "/parent/api/logout") signedIn = false;
      return signedIn || call.path === "/parent/api/logout" ? undefined : { status: 401, body: {} };
    });
    const { router } = renderPortal("/parent/attempts?client=younger");
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/parent/login");
    expect(calls.some((call) => call.path === "/parent/api/logout" && call.method === "POST")).toBe(true);
  });
});
