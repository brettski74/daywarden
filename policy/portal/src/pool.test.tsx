import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FIX_FIRST, LEVEL_RANGE } from "./sentences";
import { SUMS, fakeService, renderPortal, shown, type Call, type Reply } from "./test/portal";

const DATA = "/parent/api/parts-of-speech-pools/year-3-basics";
const WORDS = {
  id: "year-3-basics",
  name: "Year 3 basics",
  file: "/etc/daywarden/parts_of_speech_pools/year-3-basics.yaml",
  version: "v1",
  level_of_difficulty: "1.5",
  sentences: [
    { text: "The cat sat on the mat.", level_of_difficulty: "", parts: [{ name: "noun", words: [1, 5] }, { name: "verb", words: [2] }] },
    { text: "Dry the dishes with a dry towel.", level_of_difficulty: "2", parts: [{ name: "verb", words: [0] }, { name: "adjective", words: [5] }] },
  ],
  problems: [],
  tasks: ["words"],
};
const LIST = {
  pools: [
    { id: "other", name: "other", level_of_difficulty: "", sentences: 1 },
    { id: "year-3-basics", name: "Year 3 basics", level_of_difficulty: "1.5", sentences: 2 },
  ],
};
const DONE = { message: "Saved Year 3 basics. The decisions, observations, and autoconfig services are using it.", warnings: [] };

async function openWords(handler?: (call: Call) => Reply | undefined, data: unknown = WORDS) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    if (call.path === "/parent/api/parts-of-speech-pools" && call.method === "GET") return { body: LIST };
    return call.path === DATA && call.method === "GET" ? { body: data } : undefined;
  });
  const view = renderPortal("/parent/assets/parts-of-speech-pools/year-3-basics");
  await screen.findByRole("heading", { name: "Year 3 basics" });
  return { calls, router: view.router };
}

const sentence = (number: number) => screen.getByRole("region", { name: `Sentence ${number}` });
const cells = (block: HTMLElement) => [...block.querySelectorAll("td[data-row]")].map((cell) => cell.textContent);
const names = (block: HTMLElement) => within(block).getAllByRole("textbox", { name: "Part of speech" });
const status = () => screen.getByRole("status");
const save = () => screen.getByRole("button", { name: "Save" });
const altN = () => userEvent.keyboard("{Alt>}n{/Alt}");

function selected(input: HTMLElement) {
  const box = input as HTMLInputElement;
  return box.selectionStart === 0 && box.selectionEnd === box.value.length;
}

describe("a pool page", () => {
  it("shows the name and level of difficulty, then each sentence with its rows, and counts them in the status bar", async () => {
    await openWords();
    const settings = screen.getByRole("group", { name: "Pool" });
    expect(within(settings).getByRole("textbox", { name: "Name" })).toHaveValue("Year 3 basics");
    expect(within(settings).getByRole("textbox", { name: "Name" })).toHaveAttribute("readonly");
    expect(within(settings).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveValue(1.5);
    expect(within(settings).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveAttribute("placeholder", "1");
    expect(within(settings).getByText("Level of Difficulty")).toHaveAttribute("title", "level_of_difficulty");
    expect(sentence(1)).toHaveTextContent("The cat sat on the mat.");
    expect(names(sentence(1)).map((input) => (input as HTMLInputElement).value)).toEqual(["noun", "verb"]);
    expect(cells(sentence(1))).toEqual(["cat, mat", "sat"]);
    expect(within(sentence(2)).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveValue(2);
    expect(within(sentence(1)).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveAttribute("placeholder", "1.5");
    expect(status()).toHaveTextContent("2 sentences. None with problems.");
    expect(screen.getByRole("button", { name: "Add sentence" })).toHaveAttribute("title", "Add sentence (Alt+N)");
    for (const name of ["Edit sentence", "Delete sentence", "Add row"]) {
      expect(within(sentence(1)).getByRole("button", { name })).toHaveAttribute("title", name);
    }
  });

  it("offers only the words the mouse could pick up to Tab: unsorted ones in the sentence and those in cells", async () => {
    await openWords();
    const words = within(sentence(1))
      .getAllByRole("button")
      .filter((button) => button.hasAttribute("data-word"))
      .map((button) => button.textContent);
    expect(words).toEqual(["The", "on", "the", "cat", "mat", "sat"]);
  });
});

describe("sorting with the keyboard", () => {
  it("opens a menu of the rows under an unsorted word and sorts it into the chosen one", async () => {
    await openWords();
    const on = within(sentence(1)).getByRole("button", { name: "on" });
    on.focus();
    await userEvent.keyboard("{Enter}");
    const menu = screen.getByRole("menu", { name: "Sort on" });
    expect(menu).toHaveFocus();
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["noun", "verb"]);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(cells(sentence(1))).toEqual(["cat, mat", "sat, on"]);
    expect(within(sentence(1)).getByRole("button", { name: "on" }).closest("td")).not.toBeNull();
    expect(within(sentence(1)).getByRole("button", { name: "on" })).toHaveFocus();
    expect(sentence(1).querySelectorAll("td[data-changed]")).toHaveLength(1);
    expect(screen.getByRole("banner")).toHaveTextContent("Unsaved changes");
  });

  it("offers a sorted word the other rows and Not sorted, and Escape changes nothing", async () => {
    await openWords();
    const cat = within(sentence(1)).getByRole("button", { name: "cat" });
    cat.focus();
    await userEvent.keyboard(" ");
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["verb", "Not sorted"]);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(cat).toHaveFocus();
    expect(cells(sentence(1))).toEqual(["cat, mat", "sat"]);

    await userEvent.keyboard("{Enter}{End}{Enter}");
    expect(cells(sentence(1))).toEqual(["mat", "sat"]);
    expect(within(sentence(1)).getByRole("button", { name: "cat" }).closest(".pos-text")).not.toBeNull();
    expect(within(sentence(1)).getByRole("button", { name: "cat" })).toHaveFocus();
  });

  it("shows a row with no name as (no name)", async () => {
    await openWords();
    await userEvent.clear(names(sentence(1))[1]);
    within(sentence(1)).getByRole("button", { name: "on" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["noun", "(no name)"]);
  });
});

describe("sorting with the mouse", () => {
  function drag(word: HTMLElement, onto: Element) {
    document.elementFromPoint = () => onto;
    const fire = (target: EventTarget, type: string, x: number) =>
      act(() => {
        target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10 }));
      });
    fire(word, "pointerdown", 10);
    fire(document, "pointermove", 40);
    fire(document, "pointerup", 40);
  }

  it("lights a sorted word in the sentence and in its cell while the pointer is over either", async () => {
    await openWords();
    const inCell = within(sentence(1)).getByRole("button", { name: "mat" });
    const inSentence = sentence(1).querySelector(`.pos-text [data-word="${inCell.dataset.word}"]`) as HTMLElement;
    for (const hovered of [inCell, inSentence]) {
      act(() => {
        hovered.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
      });
      expect(inCell).toHaveAttribute("data-lit");
      expect(inSentence).toHaveAttribute("data-lit");
      act(() => {
        hovered.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body }));
      });
      expect(inCell).not.toHaveAttribute("data-lit");
      expect(inSentence).not.toHaveAttribute("data-lit");
    }
  });

  it("marks a word dragged from its cell as held in the cell and in the sentence", async () => {
    await openWords();
    const inCell = within(sentence(1)).getByRole("button", { name: "mat" });
    const inSentence = sentence(1).querySelector(`.pos-text [data-word="${inCell.dataset.word}"]`) as HTMLElement;
    document.elementFromPoint = () => null;
    act(() => {
      inCell.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10 }));
      document.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientX: 40, clientY: 10 }));
    });
    expect(inCell).toHaveAttribute("data-held");
    expect(inSentence).toHaveAttribute("data-held");
    act(() => {
      document.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, clientX: 40, clientY: 10 }));
    });
  });

  it("adds a word dropped on a right-hand cell of its own block to the end of it", async () => {
    await openWords();
    drag(within(sentence(1)).getByRole("button", { name: "on" }), sentence(1).querySelectorAll("td[data-row]")[0]);
    expect(cells(sentence(1))).toEqual(["cat, mat, on", "sat"]);
  });

  it("takes no drop on a name cell or on another block", async () => {
    await openWords();
    drag(within(sentence(1)).getByRole("button", { name: "on" }), sentence(1).querySelectorAll("th")[0]);
    drag(within(sentence(1)).getByRole("button", { name: "on" }), sentence(2).querySelectorAll("td[data-row]")[0]);
    expect(cells(sentence(1))).toEqual(["cat, mat", "sat"]);
    expect(cells(sentence(2))).toEqual(["Dry", "dry"]);
  });

  it("sorts the two dry words as separate words, into different rows", async () => {
    await openWords();
    const [verb, adjective] = sentence(2).querySelectorAll("td[data-row]");
    drag(within(sentence(2)).getByRole("button", { name: "dry" }), verb);
    expect(cells(sentence(2))).toEqual(["Dry, dry", ""]);
    drag(within(sentence(2)).getByRole("button", { name: "Dry" }), adjective);
    expect(cells(sentence(2))).toEqual(["dry", "Dry"]);
  });
});

describe("editing a sentence", () => {
  it("turns the sentence into a focused box with the cursor at the end, and Enter moves to the first row name", async () => {
    await openWords();
    await userEvent.click(within(sentence(1)).getByRole("button", { name: "Edit sentence" }));
    const box = within(sentence(1)).getByRole("textbox", { name: "Sentence" }) as HTMLInputElement;
    expect(box).toHaveFocus();
    expect(box.selectionStart).toBe(box.value.length);
    await userEvent.clear(box);
    await userEvent.type(box, "The dog sat on the mat.{Enter}");
    expect(within(sentence(1)).queryByRole("textbox", { name: "Sentence" })).not.toBeInTheDocument();
    expect(names(sentence(1))[0]).toHaveFocus();
    expect(selected(names(sentence(1))[0])).toBe(true);
    expect(cells(sentence(1))).toEqual(["mat", "sat"]);
    expect(sentence(1)).toHaveTextContent("No longer in the sentence, so taken out of the table: cat.");
    expect(sentence(1).querySelector(".pos-sentence")).toHaveAttribute("data-changed");
  });

  it("puts back the text with Escape and focuses the edit button", async () => {
    await openWords();
    const edit = within(sentence(1)).getByRole("button", { name: "Edit sentence" });
    await userEvent.click(edit);
    await userEvent.type(within(sentence(1)).getByRole("textbox", { name: "Sentence" }), " Again.{Escape}");
    expect(sentence(1)).toHaveTextContent("The cat sat on the mat.");
    expect(edit).toHaveFocus();
    expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes");
  });

  it("keeps the text and the focus when the edit button is pressed again", async () => {
    await openWords();
    const edit = within(sentence(1)).getByRole("button", { name: "Edit sentence" });
    await userEvent.click(edit);
    await userEvent.type(within(sentence(1)).getByRole("textbox", { name: "Sentence" }), " Again.");
    await userEvent.click(edit);
    expect(within(sentence(1)).queryByRole("textbox", { name: "Sentence" })).not.toBeInTheDocument();
    expect(sentence(1)).toHaveTextContent("The cat sat on the mat. Again.");
    expect(edit).toHaveFocus();
  });

  it("asks before deleting a sentence whose text was cleared, and Cancel puts the text back", async () => {
    await openWords();
    const edit = within(sentence(1)).getByRole("button", { name: "Edit sentence" });
    await userEvent.click(edit);
    await userEvent.clear(within(sentence(1)).getByRole("textbox", { name: "Sentence" }));
    await userEvent.keyboard("{Enter}");
    const dialog = screen.getByRole("alertdialog", { name: "Delete this sentence?" });
    expect(dialog).toHaveTextContent('"The cat sat on the mat."');
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(sentence(1)).toHaveTextContent("The cat sat on the mat.");
    expect(within(sentence(1)).queryByRole("textbox", { name: "Sentence" })).not.toBeInTheDocument();
    expect(edit).toHaveFocus();

    await userEvent.click(edit);
    await userEvent.clear(within(sentence(1)).getByRole("textbox", { name: "Sentence" }));
    await userEvent.tab();
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(sentence(1)).toHaveTextContent("Dry the dishes with a dry towel.");
    expect(screen.queryByRole("region", { name: "Sentence 2" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add sentence" })).toHaveFocus();
  });
});

describe("rows", () => {
  it("moves through the row names with Enter, adds a row after the last, and removes an empty one", async () => {
    await openWords();
    const [noun, verb] = names(sentence(1));
    noun.focus();
    await userEvent.keyboard("{Enter}");
    expect(verb).toHaveFocus();
    expect(selected(verb)).toBe(true);
    await userEvent.keyboard("{Enter}");
    expect(names(sentence(1))).toHaveLength(3);
    expect(names(sentence(1))[2]).toHaveFocus();
    expect(names(sentence(1))[2].closest("tr")).toHaveAttribute("data-changed");
    await userEvent.keyboard("{Enter}");
    expect(names(sentence(1))).toHaveLength(2);
    expect(within(sentence(1)).getByRole("button", { name: "Add row" })).toHaveFocus();
    expect(names(sentence(1))[0]).toHaveAttribute("maxlength", "20");
  });

  it("asks before Enter removes an emptied row that has words, and the remove button does not ask", async () => {
    await openWords();
    const [noun] = names(sentence(1));
    await userEvent.clear(noun);
    expect(sentence(1)).toHaveTextContent("Every row needs a name.");
    await userEvent.keyboard("{Enter}");
    const dialog = screen.getByRole("alertdialog", { name: "Remove this row?" });
    expect(dialog).toHaveTextContent("Its words go back to the sentence.");
    await userEvent.keyboard("{Escape}");
    expect(names(sentence(1))[0]).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }));
    expect(cells(sentence(1))).toEqual(["sat"]);
    expect(names(sentence(1))[0]).toHaveFocus();

    await userEvent.click(within(sentence(1)).getAllByRole("button", { name: "Remove row" })[0]);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(cells(sentence(1))).toEqual([]);
    expect(within(sentence(1)).getByRole("button", { name: "sat" }).closest(".pos-text")).not.toBeNull();
  });
});

describe("adding and deleting sentences", () => {
  it("adds a sentence with Alt+N while typing elsewhere, with the rows of the one above and its text in edit mode", async () => {
    await openWords();
    await userEvent.click(within(sentence(1)).getByRole("spinbutton", { name: "Level of Difficulty" }));
    await altN();
    const added = sentence(3);
    expect(within(added).getByRole("textbox", { name: "Sentence" })).toHaveFocus();
    expect(names(added).map((input) => (input as HTMLInputElement).value)).toEqual(["verb", "adjective"]);
    expect(cells(added)).toEqual(["", ""]);
    expect(added).toHaveAttribute("data-changed");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Sentence 3" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add sentence" })).toHaveFocus();
  });

  it("adds nothing with Alt+N while leaving an edit asks whether to delete, or while a dialog is open", async () => {
    await openWords();
    await userEvent.click(within(sentence(1)).getByRole("button", { name: "Edit sentence" }));
    await userEvent.clear(within(sentence(1)).getByRole("textbox", { name: "Sentence" }));
    await altN();
    expect(screen.getByRole("alertdialog", { name: "Delete this sentence?" })).toBeInTheDocument();
    await altN();
    expect(screen.queryByRole("region", { name: "Sentence 3" })).not.toBeInTheDocument();
  });

  it("asks before the delete button removes a sentence, then focuses Add sentence", async () => {
    await openWords();
    await userEvent.click(within(sentence(2)).getByRole("button", { name: "Delete sentence" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete this sentence?" });
    expect(dialog).toHaveTextContent('"Dry the dishes with a dry towel."');
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(screen.queryByRole("region", { name: "Sentence 2" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add sentence" })).toHaveFocus();
    expect(status()).toHaveTextContent("1 sentence. None with problems.");
  });

  it("says when there are no sentences at all", async () => {
    await openWords(undefined, { ...WORDS, sentences: [] });
    expect(screen.getByText("There are no sentences. Add at least one.")).toBeInTheDocument();
  });
});

describe("warnings, problems, and saving", () => {
  it("warns about a name that is not a part of speech but still saves", async () => {
    await openWords();
    const [noun] = names(sentence(1));
    await userEvent.clear(noun);
    await userEvent.type(noun, "Subject");
    expect(sentence(1)).toHaveTextContent('"Subject" is not a recognized part of speech.');
    expect(noun).toHaveAttribute("data-changed");
    expect(save()).toBeEnabled();
  });

  it("will not save while a problem remains, and Ctrl+S says why", async () => {
    const { calls } = await openWords();
    await userEvent.clear(names(sentence(1))[0]);
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", FIX_FIRST);
    expect(status()).toHaveTextContent("2 sentences. 1 with problems.");
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(status()).toHaveTextContent(FIX_FIRST);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("adds a sentence from the keyboard and saves it with the rest", async () => {
    const { calls } = await openWords((call) =>
      call.method === "POST" ? { body: DONE } : undefined,
    );
    await altN();
    await userEvent.keyboard("The fox ran.{Enter}");
    expect(names(sentence(3))[0]).toHaveFocus();
    await userEvent.keyboard("noun{Enter}");
    expect(names(sentence(3))[1]).toHaveFocus();
    await userEvent.keyboard("{Enter}{Enter}");
    expect(names(sentence(3))).toHaveLength(2);
    within(sentence(3)).getByRole("button", { name: "fox" }).focus();
    await userEvent.keyboard("{Enter}{Enter}");
    within(sentence(3)).getByRole("button", { name: "ran" }).focus();
    await userEvent.keyboard("{Enter}{ArrowDown}{Enter}");
    expect(cells(sentence(3))).toEqual(["fox", "ran"]);
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText(/^Saved Year 3 basics\./)).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toMatchObject({
      version: "v1",
      level_of_difficulty: "1.5",
      sentences: [
        { origin: 0, text: "The cat sat on the mat." },
        { origin: 1, text: "Dry the dishes with a dry towel.", level_of_difficulty: "2" },
        { origin: null, text: "The fox ran.", level_of_difficulty: "", parts: [{ name: "noun", words: [1] }, { name: "adjective", words: [2] }] },
      ],
    });
    await waitFor(() => expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes"));
  });
});

describe("levels of difficulty", () => {
  it("will not save a pool or sentence level outside 0.5 through 10, and says why", async () => {
    const { calls } = await openWords();
    const pool = within(screen.getByRole("group", { name: "Pool" })).getByRole("spinbutton", { name: "Level of Difficulty" });
    await userEvent.clear(pool);
    await userEvent.type(pool, "11");
    expect(screen.getByText(LEVEL_RANGE)).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", LEVEL_RANGE);
    await userEvent.clear(pool);
    expect(within(sentence(1)).getByRole("spinbutton", { name: "Level of Difficulty" })).toHaveAttribute("placeholder", "1");
    const own = within(sentence(1)).getByRole("spinbutton", { name: "Level of Difficulty" });
    await userEvent.type(own, "0.25");
    expect(sentence(1)).toHaveTextContent(LEVEL_RANGE);
    expect(save()).toBeDisabled();
    await userEvent.clear(own);
    await userEvent.type(own, "3");
    expect(save()).toBeEnabled();
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("sends the pool's level as typed with the sentences", async () => {
    const { calls } = await openWords((call) => (call.method === "POST" ? { body: DONE } : undefined));
    const pool = within(screen.getByRole("group", { name: "Pool" })).getByRole("spinbutton", { name: "Level of Difficulty" });
    await userEvent.clear(pool);
    await userEvent.type(pool, "2.5");
    expect(pool).toHaveAttribute("data-changed");
    await userEvent.click(save());
    await screen.findByText(/^Saved Year 3 basics\./);
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ level_of_difficulty: "2.5" });
  });
});

describe("renaming and deleting a pool", () => {
  it("renames the pool from the name box and Save, and Escape puts the old name back", async () => {
    const { calls } = await openWords((call) =>
      call.path === `${DATA}/rename` ? { body: { message: "Renamed Year 3 basics to Basics.", warnings: [], pool: { id: "year-3-basics", name: "Basics" } } } : undefined,
    );
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(name).toHaveValue("Year 3 basics");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.clear(name);
    expect(save()).toBeDisabled();
    expect(screen.getByText("Give the pool a name.")).toBeInTheDocument();
    await userEvent.type(name, "Basics");
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Renamed Year 3 basics to Basics.")).toBeInTheDocument();
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({ name: "Basics", version: "v1" });
  });

  it("will not start a rename while there are unsaved changes", async () => {
    await openWords();
    await userEvent.click(within(sentence(2)).getByRole("button", { name: "Delete sentence" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
  });

  it("asks before deleting, and shows the refusal when a task uses the pool", async () => {
    const refusal = "Year 3 basics cannot be deleted while a task uses it: words. Take it out of those tasks first.";
    const { calls } = await openWords((call) => (call.path === `${DATA}/delete` ? { status: 400, body: { error: refusal } } : undefined));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete this pool?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Year 3 basics" })).toBeInTheDocument();
  });

  it("returns to the list after a delete, which no longer lists the pool", async () => {
    let deleted = false;
    const { router } = await openWords((call) => {
      if (call.path === `${DATA}/delete`) {
        deleted = true;
        return { body: { message: "Deleted Year 3 basics.", warnings: [] } };
      }
      if (call.path === "/parent/api/parts-of-speech-pools" && call.method === "GET") return { body: deleted ? { pools: [LIST.pools[0]] } : LIST };
      return undefined;
    });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("heading", { name: "Parts of Speech Pools" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/assets/parts-of-speech-pools");
    expect(status()).toHaveTextContent("Deleted Year 3 basics.");
    expect(screen.queryByRole("link", { name: "Year 3 basics" })).not.toBeInTheDocument();
  });
});

describe("the pool list", () => {
  async function openList(handler?: (call: Call) => Reply | undefined) {
    const calls = fakeService((call) => handler?.(call) ?? (call.path === "/parent/api/parts-of-speech-pools" ? { body: LIST } : call.path === DATA ? { body: WORDS } : undefined));
    const view = renderPortal("/parent/assets/parts-of-speech-pools");
    await screen.findByRole("heading", { name: "Parts of Speech Pools" });
    return { calls, router: view.router };
  }

  it("lists every pool by name, linked to its page, with its level of difficulty and sentence count", async () => {
    await openList();
    const rows = screen.getAllByRole("row").slice(1).map((row) => [...row.querySelectorAll("td")].map((cell) => cell.textContent));
    expect(rows).toEqual([
      ["other", "1", "1"],
      ["Year 3 basics", "1.5", "2"],
    ]);
    expect(screen.getByRole("link", { name: "Year 3 basics" })).toHaveAttribute("href", "/parent/assets/parts-of-speech-pools/year-3-basics");
    expect(status()).toHaveTextContent("2 pools.");
  });

  it("makes a pool from New pool and opens its page, and shows a refused name in the dialog", async () => {
    const { calls, router } = await openList((call) => {
      if (call.method !== "POST") return undefined;
      const name = (call.body as { name: string }).name;
      return name === "other"
        ? { status: 400, body: { error: "A pool named other already exists." } }
        : { body: { message: "Made the pool Year 3 basics.", warnings: [], pool: { id: "year-3-basics", name } } };
    });
    await userEvent.click(screen.getByRole("button", { name: "New pool" }));
    await userEvent.keyboard("other{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A pool named other already exists.");
    const box = screen.getByRole("textbox", { name: "Name" });
    await userEvent.clear(box);
    await userEvent.type(box, "Year 3 basics{Enter}");
    expect(await screen.findByRole("heading", { name: "Year 3 basics" })).toBeInTheDocument();
    expect(shown(router)).toBe("/parent/assets/parts-of-speech-pools/year-3-basics");
    expect(status()).toHaveTextContent("Made the pool Year 3 basics.");
    expect(calls.filter((call) => call.method === "POST").map((call) => call.body)).toEqual([{ name: "other" }, { name: "Year 3 basics" }]);
  });

  it("is reached from the Asset Administration group in the sidebar", async () => {
    await openList();
    const group = screen.getByRole("button", { name: "Asset Administration" });
    expect(group).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Parts of Speech Pools" })).toHaveAttribute("href", "/parent/assets/parts-of-speech-pools");
  });

  it("sends a signed-out parent to sign-in, returning to the pool page", async () => {
    fakeService(() => ({ status: 401, body: { error: "Sign in to see this." } }));
    const { router } = renderPortal("/parent/assets/parts-of-speech-pools/year-3-basics");
    await screen.findByRole("button", { name: "Login" });
    expect(router.state.location.pathname).toBe("/parent/login");
    expect(new URLSearchParams(router.state.location.search).get("next")).toBe("/parent/assets/parts-of-speech-pools/year-3-basics");
  });
});

describe("a parts of speech task page", () => {
  it("keeps the task's own settings and sends the parent to the pools for its sentences", async () => {
    const task = { ...SUMS, name: "words", type: "parts_of_speech", parts_of_speech: { settings: { timeout: "45s", correct_answers_required: "" } } };
    const calls = fakeService((call) =>
      call.path === "/parent/api/tasks/parts_of_speech/words"
        ? call.method === "GET"
          ? { body: task }
          : { body: { message: "Saved words.", warnings: [] } }
        : undefined,
    );
    renderPortal("/parent/tasks/parts_of_speech/words");
    await screen.findByRole("heading", { name: "words" });
    expect(screen.queryByRole("button", { name: "Add sentence" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Parts of Speech Pools" })).toHaveAttribute("href", "/parent/assets/parts-of-speech-pools");
    const timeout = screen.getByRole("textbox", { name: "Timeout" });
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "60s");
    await userEvent.click(save());
    await screen.findByText("Saved words.");
    const post = calls.find((call) => call.method === "POST")?.body as Record<string, unknown>;
    expect(post.settings).toEqual({ timeout: "60s", correct_answers_required: "" });
    expect(post).not.toHaveProperty("sentences");
  });
});
