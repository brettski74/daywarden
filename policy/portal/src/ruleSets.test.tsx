import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ruleFrom, ruleOut, rulesFrom, rulesOut, withCondition } from "./ruleSets";
import { fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const DATA = {
  version: "v1",
  file: "/etc/daywarden/policy.yaml",
  choices: {
    time_window: ["bedtime", "evening"],
    site_group: ["school", "games", "default"],
    client_group: ["younger", "default"],
    quota: ["entertainment", "reading"],
  },
  items: [
    {
      name: "gate",
      file: null,
      rules: [
        { condition: "time_window", window: "bedtime", when_true: { action: "deny", message: "Bedtime." } },
        { condition: "site_group", groups: ["school"], when_true: { action: "evaluate", ruleset: "meter" }, when_false: { action: "continue" } },
        { condition: "always", when_true: { action: "allow" } },
      ],
      users: [{ kind: "entry", name: "", text: "the household's entry" }],
    },
    {
      name: "nested",
      file: "extra.yaml",
      rules: [
        {
          condition: "site_group",
          groups: ["school", "games"],
          when_true: { action: "evaluate", rules: [{ condition: "tasks_required", required: 2, when_false: { action: "redirect", location: "revision_task" } }] },
        },
      ],
      users: [{ kind: "rule_set", name: "gate", text: "rule set gate, rule 2" }],
    },
    {
      name: "meter",
      file: null,
      rules: [],
      users: [
        { kind: "quota", name: "entertainment", text: "quota entertainment" },
        { kind: "rule_set", name: "gate", text: "rule set gate, rule 2" },
      ],
    },
  ],
};
const DONE = { message: "Saved the rule set gate.", warnings: [] };

async function open(path: string, handler?: (call: Call) => Reply | undefined) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    return call.path === "/parent/api/policy/rule-sets" && call.method === "GET" ? { body: DATA } : undefined;
  });
  const view = renderPortal(`/parent/policy/rule-sets${path}`);
  await screen.findByRole("heading", { level: 1 });
  return { calls, router: view.router };
}

const save = () => screen.getByRole("button", { name: "Save" });
const rule = (name: string) => screen.getByRole("group", { name });
const posts = (calls: Call[]) => calls.filter((call) => call.method === "POST" && call.path === "/parent/api/policy/rule-sets");
const select = (within_: HTMLElement, name: string, nth = 0) => within(within_).getAllByLabelText(name, { selector: "select" })[nth];

describe("reading and writing a rule", () => {
  it("writes one window or group as window or group and several as windows or groups", () => {
    const one = ruleFrom({ condition: "site_group", groups: ["school"], when_true: { action: "allow" } });
    expect(ruleOut({ ...one, raw: null, names: ["school"] })).toEqual({ condition: "site_group", group: "school", when_true: { action: "allow" } });
    expect(ruleOut({ ...one, raw: null, names: ["school", "games"] })).toEqual({ condition: "site_group", groups: ["school", "games"], when_true: { action: "allow" } });
  });

  it("keeps the file's own text for a rule that means the same, and leaves a continue action out of one that changed", () => {
    const written = { condition: "site_group", groups: ["school"], when_true: { action: "continue" }, when_false: { action: "deny", message: "No." } };
    const same = ruleFrom(written);
    expect(ruleOut(same)).toBe(written);
    expect(ruleOut({ ...same, names: ["games"] })).toEqual({ condition: "site_group", group: "games", when_false: { action: "deny", message: "No." } });
  });

  it("clears the parameters a new condition does not take, and keeps a quota between the two quota conditions", () => {
    const [timed] = rulesFrom([{ condition: "time_remaining", quota: "entertainment", when_false: { action: "deny", message: "Up." } }]);
    expect(withCondition(timed, "volume_remaining").quota).toBe("entertainment");
    expect(withCondition(timed, "tasks_required").quota).toBe("");
    const [grouped] = rulesFrom([{ condition: "site_group", group: "school" }]);
    expect(withCondition(grouped, "client_group").names).toEqual([]);
    expect(rulesOut([withCondition(grouped, "always")])).toEqual([{ condition: "always" }]);
  });
});

describe("the rule set list", () => {
  it("lists each rule set with its rule count and what uses it, each name and user a link", async () => {
    await open("");
    const row = screen.getByRole("link", { name: "gate" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "the household's entry" })).toHaveAttribute("href", "/parent/policy/household");
    const meter = screen.getByRole("link", { name: "meter" }).closest("tr") as HTMLElement;
    expect(within(meter).getByRole("link", { name: "quota entertainment" })).toHaveAttribute("href", "/parent/policy/quotas");
    expect(within(meter).getByRole("link", { name: "rule set gate, rule 2" })).toHaveAttribute("href", "/parent/policy/rule-sets/gate");
  });

  it("writes a new empty rule set at once and opens its page, and keeps the dialog open with the reason when refused", async () => {
    const user = userEvent.setup();
    const made = { ...DATA, version: "v2", items: [...DATA.items, { name: "fresh", file: null, rules: [], users: [] }] };
    let version = "v1";
    const { calls, router } = await open("", (call) => {
      if (call.method === "POST") {
        const name = (call.body as { items: { name: string }[] }).items[0].name;
        if (name === "gate") return { status: 400, body: { error: "A rule set named gate already exists, in policy.yaml." } };
        version = "v2";
        return { body: { message: "Created the rule set fresh.", warnings: [] } };
      }
      return call.path === "/parent/api/policy/rule-sets" ? { body: version === "v1" ? DATA : made } : undefined;
    });
    await user.click(screen.getByRole("button", { name: "New Rule Set" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "gate{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A rule set named gate already exists");
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "fresh{Enter}");
    await waitFor(() => expect(shown(router)).toBe("/parent/policy/rule-sets/fresh"));
    expect(posts(calls).at(-1)?.body).toEqual({ version: "v1", items: [{ name: "fresh", new: true, fields: { rules: [] } }], deleted: [] });
  });
});

describe("a rule set's page", () => {
  it("shows its rules in order, numbered, with their conditions and actions as written", async () => {
    await open("/gate");
    expect(screen.getByRole("heading", { level: 1, name: "gate" })).toBeInTheDocument();
    expect(select(rule("Rule 1"), "Condition")).toHaveValue("time_window");
    expect(within(rule("Rule 1")).getByRole("button", { name: /Windows/ })).toHaveTextContent("bedtime");
    expect(select(rule("Rule 1"), "True action")).toHaveValue("deny");
    expect(within(rule("Rule 1")).getByLabelText("Message")).toHaveValue("Bedtime.");
    expect(select(rule("Rule 2"), "False action")).toHaveValue("continue");
    expect(within(rule("Rule 3")).queryByText("False action")).toBeNull();
    expect(screen.getByRole("link", { name: "the household's entry" })).toHaveAttribute("href", "/parent/policy/household");
  });

  it("shows an evaluate of a named rule set as a link, and following it asks first when there are unsaved changes", async () => {
    const user = userEvent.setup();
    const { router } = await open("/gate");
    const link = within(rule("Rule 2")).getByRole("link", { name: "Open meter" });
    expect(link).toHaveAttribute("href", "/parent/policy/rule-sets/meter");
    await user.selectOptions(select(rule("Rule 1"), "True action"), "allow");
    await user.click(link);
    expect(await screen.findByText("Leave this page?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/policy/rule-sets/meter"));
  });

  it("writes nothing when a field is changed and changed back", async () => {
    const user = userEvent.setup();
    const { calls } = await open("/gate");
    const message = within(rule("Rule 1")).getByLabelText("Message");
    await user.type(message, "!");
    expect(save()).toBeEnabled();
    await user.type(message, "{Backspace}");
    expect(save()).toBeDisabled();
    expect(posts(calls)).toEqual([]);
  });

  it("changing a condition clears the parameters the new one does not take", async () => {
    const user = userEvent.setup();
    await open("/gate");
    await user.selectOptions(select(rule("Rule 1"), "Condition"), "tasks_required");
    expect(within(rule("Rule 1")).queryByRole("button", { name: /Windows/ })).toBeNull();
    await user.type(within(rule("Rule 1")).getByLabelText("Required"), "1");
    await user.selectOptions(select(rule("Rule 1"), "Condition"), "time_remaining");
    expect(within(rule("Rule 1")).queryByLabelText("Required")).toBeNull();
    expect(select(rule("Rule 1"), "Quota")).toHaveValue("");
  });

  it("saves a chosen window as window and several as windows, with a continue action left out", async () => {
    const user = userEvent.setup();
    const { calls } = await open("/gate", (call) => (call.method === "POST" ? { body: DONE } : undefined));
    await user.click(within(rule("Rule 1")).getByRole("button", { name: /Windows/ }));
    await user.click(screen.getByRole("option", { name: "evening" }));
    await user.selectOptions(select(rule("Rule 2"), "True action"), "continue");
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      version: "v1",
      items: [
        {
          name: "gate",
          new: false,
          fields: {
            rules: [
              { condition: "time_window", windows: ["bedtime", "evening"], when_true: { action: "deny", message: "Bedtime." } },
              { condition: "site_group", group: "school" },
              { condition: "always", when_true: { action: "allow" } },
            ],
          },
        },
      ],
      deleted: [],
    });
    expect(await screen.findByText("Saved the rule set gate.")).toBeInTheDocument();
  });

  it("sends a deny with no message for the service to refuse, and shows its reasons", async () => {
    const user = userEvent.setup();
    await open("/gate", (call) =>
      call.method === "POST" ? { status: 400, body: { error: "This save would leave the policy unable to load, so nothing was saved.", errors: ["policy.yaml:3:5 rule 2: deny needs a message"] } } : undefined,
    );
    await user.selectOptions(select(rule("Rule 3"), "True action"), "deny");
    await user.click(save());
    expect(await screen.findByText("policy.yaml:3:5 rule 2: deny needs a message")).toBeInTheDocument();
    expect(save()).toBeEnabled();
  });

  it("starts an inline list with one empty rule, indented under its action with the same editor, and folds it", async () => {
    const user = userEvent.setup();
    await open("/gate");
    await user.selectOptions(select(rule("Rule 3"), "True action"), "evaluate");
    await user.selectOptions(select(rule("Rule 3"), "Rule Set"), "Inline rules");
    const inner = rule("Rule 3 when_true rule 1");
    expect(select(inner, "Condition")).toHaveValue("always");
    await user.selectOptions(select(inner, "True action"), "evaluate");
    await user.selectOptions(select(inner, "Rule Set"), "Inline rules");
    expect(rule("Rule 3 when_true rule 1 when_true rule 1")).toBeInTheDocument();
    await user.click(within(rule("Rule 3")).getAllByRole("button", { name: /Inline rules \(1\)/ })[0]);
    await waitFor(() => expect(screen.queryByRole("group", { name: "Rule 3 when_true rule 1" })).toBeNull());
  });

  it("makes a named rule set from an inline list: the action evaluates it, with no link until the save writes both", async () => {
    const user = userEvent.setup();
    const { calls } = await open("/nested", (call) => (call.method === "POST" ? { body: { message: "Saved.", warnings: [] } } : undefined));
    await user.click(screen.getByRole("button", { name: /Make Named Rule Set/ }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "meter{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A rule set named meter already exists");
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "nested_inner{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(select(rule("Rule 1"), "Rule Set")).toHaveValue("nested_inner");
    expect(within(rule("Rule 1")).queryByRole("link", { name: /Open nested_inner/ })).toBeNull();
    expect(within(rule("Rule 1")).getByText(/nested_inner is made when this page is saved/)).toBeInTheDocument();
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0].body).toEqual({
      version: "v1",
      items: [
        { name: "nested", new: false, fields: { rules: [{ condition: "site_group", groups: ["school", "games"], when_true: { action: "evaluate", ruleset: "nested_inner" } }] } },
        { name: "nested_inner", new: true, fields: { rules: [{ condition: "tasks_required", required: 2, when_false: { action: "redirect", location: "revision_task" } }] } },
      ],
      deleted: [],
    });
  });

  it("gives up a rule set made on the page when its action is changed away from it", async () => {
    const user = userEvent.setup();
    await open("/nested");
    await user.click(screen.getByRole("button", { name: /Make Named Rule Set/ }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "later{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.selectOptions(select(rule("Rule 1"), "True action"), "allow");
    await user.selectOptions(select(rule("Rule 1"), "True action"), "continue");
    expect(save()).toBeEnabled();
    await user.selectOptions(select(rule("Rule 1"), "True action"), "evaluate");
    expect(within(rule("Rule 1")).queryByRole("option", { name: "later" })).toBeNull();
  });

  it("adds, inserts above, deletes, and moves rules with Alt+Up and Alt+Down within their own list", async () => {
    const user = userEvent.setup();
    const { calls } = await open("/gate", (call) => (call.method === "POST" ? { body: DONE } : undefined));
    await user.keyboard("{Alt>}n{/Alt}");
    expect(rule("Rule 4")).toBeInTheDocument();
    await user.click(within(rule("Rule 4")).getByRole("button", { name: "Delete Rule 4" }));
    await user.click(screen.getByRole("button", { name: "Insert above Rule 1" }));
    expect(select(rule("Rule 1"), "Condition")).toHaveValue("always");
    expect(select(rule("Rule 2"), "Condition")).toHaveValue("time_window");
    select(rule("Rule 2"), "Condition").focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(select(rule("Rule 3"), "Condition")).toHaveValue("time_window");
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(select(rule("Rule 2"), "Condition")).toHaveValue("time_window");
    await user.click(save());
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    const sent = (posts(calls)[0].body as { items: { fields: { rules: { condition: string }[] } }[] }).items[0].fields.rules;
    expect(sent.map((each) => each.condition)).toEqual(["always", "time_window", "site_group", "always"]);
  });

  it("moves a rule by dragging its handle onto another rule", async () => {
    await open("/gate");
    const handle = within(rule("Rule 3")).getByRole("button", { name: "Move Rule 3" });
    const target = rule("Rule 1").closest("li") as HTMLElement;
    const data = { effectAllowed: "", setData: () => undefined };
    fireEvent.dragStart(handle, { dataTransfer: data });
    fireEvent.dragOver(target, { dataTransfer: data });
    fireEvent.drop(target, { dataTransfer: data });
    expect(select(rule("Rule 1"), "Condition")).toHaveValue("always");
    expect(select(rule("Rule 2"), "Condition")).toHaveValue("time_window");
  });
});

describe("Delete Rule Set", () => {
  it("asks first with Cancel as the default, then deletes at once and returns to the list", async () => {
    const user = userEvent.setup();
    const { calls, router } = await open("/nested", (call) => (call.method === "POST" ? { body: { message: "Deleted the rule set nested.", warnings: [] } } : undefined));
    await user.click(screen.getByRole("button", { name: "Delete Rule Set" }));
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(posts(calls)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Delete Rule Set" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(shown(router)).toBe("/parent/policy/rule-sets"));
    expect(posts(calls)[0].body).toEqual({ version: "v1", items: [], deleted: ["nested"] });
  });

  it("is refused while something names the rule set, and the refusal names each user", async () => {
    const user = userEvent.setup();
    const { router } = await open("/meter", (call) =>
      call.method === "POST"
        ? { status: 400, body: { error: "The rule set meter is still in use, so it was not deleted.", errors: ["Rule set meter is used by quota entertainment.", "Rule set meter is used by rule set gate, rule 2."] } }
        : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Delete Rule Set" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Rule set meter is used by quota entertainment.")).toBeInTheDocument();
    expect(screen.getByText("Rule set meter is used by rule set gate, rule 2.")).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/policy/rule-sets/meter");
  });
});

describe("Rename Rule Set", () => {
  it("is beside Save, disabled with its reason while the page has unsaved changes", async () => {
    const user = userEvent.setup();
    await open("/gate");
    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    await user.keyboard("{Alt>}n{/Alt}");
    expect(save()).toBeEnabled();
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rename" })).toHaveAttribute("title", expect.stringMatching(/Save or undo the changes/));
  });

  it("renames at once and opens the page at the new name, saying so", async () => {
    const user = userEvent.setup();
    let renamed = false;
    const after = { ...DATA, version: "v2", items: DATA.items.map((each) => (each.name === "gate" ? { ...each, name: "front-door" } : each)) };
    const { calls, router } = await open("/gate", (call) => {
      if (call.method === "POST") {
        renamed = true;
        return { body: { message: "Renamed the rule set gate to front-door.", warnings: [], name: "front-door" } };
      }
      return renamed && call.path === "/parent/api/policy/rule-sets" ? { body: after } : undefined;
    });
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByRole("textbox", { name: "New name" })).toHaveValue("gate");
    await user.clear(screen.getByRole("textbox", { name: "New name" }));
    await user.type(screen.getByRole("textbox", { name: "New name" }), "front-door{Enter}");
    await waitFor(() => expect(shown(router)).toBe("/parent/policy/rule-sets/front-door"));
    expect(await screen.findByRole("heading", { level: 1, name: "front-door" })).toBeInTheDocument();
    expect(screen.getByText("Renamed the rule set gate to front-door.")).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "POST");
    expect(sent).toMatchObject({ path: "/parent/api/policy/rule-sets/rename", body: { version: "v1", name: "gate", to: "front-door" } });
  });

  it("keeps the dialog open with the loader's reasons when the name is refused", async () => {
    const user = userEvent.setup();
    const { router } = await open("/gate", (call) =>
      call.method === "POST" ? { status: 400, body: { error: "A rule set named meter already exists, in policy.yaml." } } : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.clear(screen.getByRole("textbox", { name: "New name" }));
    await user.type(screen.getByRole("textbox", { name: "New name" }), "meter{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A rule set named meter already exists");
    expect(shown(router)).toBe("/parent/policy/rule-sets/gate");
  });
});

describe("an address with no rule set", () => {
  it("says there is no such rule set", async () => {
    await open("/missing");
    expect(screen.getByText("There is no rule set named missing.")).toBeInTheDocument();
  });
});
