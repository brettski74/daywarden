import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { NO_CAPITAL, TWICE, pasteInto, problems, newBlock } from "./capitalisation";
import { fakeService, renderPortal, type Call, type Reply } from "./test/portal";

const DATA = "/parent/api/capitalisation-pools/places";
const POOL = {
  id: "places",
  name: "Places",
  file: "/etc/daywarden/capitalisation_pools/places.yaml",
  version: "v1",
  level_of_difficulty: "1.5",
  sentences: [
    { text: "Anna flew to Paris.", level_of_difficulty: "" },
    { text: "We saw NASA in July.", level_of_difficulty: "2" },
  ],
  problems: [],
  tasks: ["caps"],
};
const LIST = { pools: [{ id: "places", name: "Places", level_of_difficulty: "1.5", sentences: 2 }] };
const DONE = { message: "Saved Places.", warnings: [] };

async function open(handler?: (call: Call) => Reply | undefined, data: unknown = POOL) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.path === "/parent/api/capitalisation-pools" && call.method === "GET") return { body: LIST };
    return call.path === DATA && call.method === "GET" ? { body: data } : undefined;
  });
  const view = renderPortal("/parent/assets/capitalisation-pools/places");
  await screen.findByRole("heading", { name: "Places" });
  return { calls, router: view.router };
}

const row = (number: number) => screen.getByRole("region", { name: `Sentence ${number}` });
const text = (number: number) => within(row(number)).getByRole("textbox", { name: "Sentence" }) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save" });

describe("the capitalisation sentence rules", () => {
  it("flags an empty sentence, one with no capital, and one already in the pool, and a bad level", () => {
    const blocks = [newBlock("Anna flew."), newBlock(""), newBlock("flew home"), newBlock("  anna   FLEW. "), { ...newBlock("Ok"), level: "11" }];
    expect(problems(blocks, 0)).toEqual([]);
    expect(problems(blocks, 1)).toEqual(["The sentence is empty."]);
    expect(problems(blocks, 2)).toEqual([NO_CAPITAL]);
    expect(problems(blocks, 3)).toEqual([TWICE]);
    expect(problems(blocks, 4)).toEqual(["Level of difficulty must be a number from 0.5 through 10."]);
  });

  it("splits a pasted block into the first line and the non-empty lines after it", () => {
    expect(pasteInto(newBlock("Hi"), 2, 2, "one")).toBeNull();
    expect(pasteInto(newBlock(""), 0, 0, "A b\n\n C d \r\nE f")).toEqual({ first: "A b", more: ["C d", "E f"] });
  });
});

describe("a capitalisation pool page", () => {
  it("shows a row for each sentence with its level of difficulty box, and counts them", async () => {
    await open();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Places");
    expect(text(1)).toHaveValue("Anna flew to Paris.");
    const own = within(row(1)).getByRole("spinbutton", { name: "Level of Difficulty" });
    expect(own).toHaveAttribute("placeholder", "1.5");
    expect(within(row(2)).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveValue(2);
    expect(within(row(1)).getByRole("button", { name: "Delete sentence" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 sentences. None with problems.");
    expect(within(screen.getByRole("navigation", { name: "Where you are" })).getByRole("link", { name: "Capitalisation Pools" })).toHaveAttribute(
      "href",
      "/parent/assets/capitalisation-pools",
    );
  });

  it("adds an empty row at the end with Alt+N and puts the cursor in it", async () => {
    await open();
    await userEvent.keyboard("{Alt>}n{/Alt}");
    expect(text(3)).toHaveFocus();
    expect(text(3)).toHaveValue("");
    expect(within(row(3)).getByText("The sentence is empty.")).toBeInTheDocument();
    expect(save()).toBeDisabled();
  });

  it("puts a pasted first line in the row and each other non-empty line in a new row below", async () => {
    await open(undefined, { ...POOL, sentences: [] });
    await userEvent.click(screen.getByRole("button", { name: "Add sentence" }));
    const box = within(screen.getByRole("region", { name: "Sentence 1" })).getByRole("textbox", { name: "Sentence" });
    fireEvent.paste(box, { clipboardData: { getData: () => "Anna flew.\n\nBob ran.\nCara sat." } });
    await waitFor(() => expect(screen.getByRole("region", { name: "Sentence 3" })).toBeInTheDocument());
    expect([1, 2, 3].map((number) => text(number).value)).toEqual(["Anna flew.", "Bob ran.", "Cara sat."]);
  });

  it("saves with Ctrl+S, sending each sentence with its place in the file", async () => {
    const { calls } = await open((call) => (call.path === DATA && call.method === "POST" ? { body: DONE } : undefined));
    await userEvent.type(text(1), "{End}!");
    await userEvent.click(within(row(2)).getByRole("button", { name: "Delete sentence" }));
    await userEvent.keyboard("{Control>}s{/Control}");
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = calls.find((call) => call.method === "POST")!.body as { sentences: unknown[]; version: string };
    expect(sent.version).toBe("v1");
    expect(sent.sentences).toEqual([{ origin: 0, text: "Anna flew to Paris.!", level_of_difficulty: "" }]);
  });

  it("blocks Save for a sentence with no capital and says why under the row", async () => {
    await open();
    await userEvent.clear(text(2));
    await userEvent.type(text(2), "no capitals here");
    expect(within(row(2)).getByText(NO_CAPITAL)).toBeInTheDocument();
    expect(save()).toBeDisabled();
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(screen.getByRole("status")).toHaveTextContent("Fix the problems marked under the sentences first.");
  });

  it("lists the pool pages in the Asset Administration sidebar", async () => {
    await open();
    expect(screen.getAllByRole("link", { name: "Capitalisation Pools" }).some((link) => link.getAttribute("href") === "/parent/assets/capitalisation-pools")).toBe(true);
    expect(screen.getByRole("link", { name: "Parts of Speech Pools" })).toHaveAttribute("href", "/parent/assets/parts-of-speech-pools");
  });
});
