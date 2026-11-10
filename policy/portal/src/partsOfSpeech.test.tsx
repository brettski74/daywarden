import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FIX_FIRST } from "./sentences";
import { SUMS, fakeService, renderPortal, type Call, type Reply } from "./test/portal";

const WORDS = {
  ...SUMS,
  name: "words",
  type: "parts_of_speech",
  parts_of_speech: {
    settings: { timeout: "45s", correct_answers_required: "" },
    sentences: [
      { text: "The cat sat on the mat.", timeout: "", parts: [{ name: "noun", words: [1, 5] }, { name: "verb", words: [2] }] },
      { text: "Dry the dishes with a dry towel.", timeout: "2m", parts: [{ name: "verb", words: [0] }, { name: "adjective", words: [5] }] },
    ],
    problems: [],
  },
};

async function openWords(handler?: (call: Call) => Reply | undefined, data: unknown = WORDS) {
  const calls = fakeService((call) => {
    const answered = handler?.(call);
    if (answered) return answered;
    return call.path === "/parent/api/tasks/words" && call.method === "GET" ? { body: data } : undefined;
  });
  renderPortal("/parent/tasks/words");
  await screen.findByRole("heading", { name: "words" });
  return calls;
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

describe("the parts of speech area of a task page", () => {
  it("shows the settings, then each sentence with its rows, and counts them in the status bar", async () => {
    await openWords();
    const settings = screen.getByRole("group", { name: "Parts of speech settings" });
    expect(within(settings).getByRole("textbox", { name: "Timeout" })).toHaveValue("45s");
    expect(within(settings).getByRole("textbox", { name: "Timeout" })).toHaveAttribute("placeholder", "90s");
    expect(within(settings).getByRole("textbox", { name: "Correct Answers Required" })).toHaveAttribute("placeholder", "2");
    expect(within(settings).getByText("Correct Answers Required")).toHaveAttribute("title", "correct_answers_required");
    expect(sentence(1)).toHaveTextContent("The cat sat on the mat.");
    expect(names(sentence(1)).map((input) => (input as HTMLInputElement).value)).toEqual(["noun", "verb"]);
    expect(cells(sentence(1))).toEqual(["cat, mat", "sat"]);
    expect(within(sentence(2)).getByRole("textbox", { name: "Timeout" })).toHaveValue("2m");
    expect(within(sentence(1)).getByRole("textbox", { name: "Timeout" })).toHaveAttribute("placeholder", "45s");
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
    await userEvent.click(within(sentence(1)).getByRole("textbox", { name: "Timeout" }));
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
    await openWords(undefined, { ...WORDS, parts_of_speech: { ...WORDS.parts_of_speech, sentences: [] } });
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
    const calls = await openWords();
    await userEvent.clear(names(sentence(1))[0]);
    expect(save()).toBeDisabled();
    expect(save()).toHaveAttribute("title", FIX_FIRST);
    expect(status()).toHaveTextContent("2 sentences. 1 with problems.");
    await userEvent.keyboard("{Control>}s{/Control}");
    expect(status()).toHaveTextContent(FIX_FIRST);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("adds a sentence from the keyboard and saves it with the rest", async () => {
    const calls = await openWords((call) =>
      call.method === "POST" ? { body: { message: "Saved words. The decisions, observations, and autoconfig services are using it.", warnings: [] } } : undefined,
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
    expect(await screen.findByText(/^Saved words\./)).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toMatchObject({
      settings: { timeout: "45s", correct_answers_required: "" },
      sentences: [
        { origin: 0, text: "The cat sat on the mat." },
        { origin: 1, text: "Dry the dishes with a dry towel.", timeout: "2m" },
        { origin: null, text: "The fox ran.", timeout: "", parts: [{ name: "noun", words: [1] }, { name: "adjective", words: [2] }] },
      ],
    });
    await waitFor(() => expect(screen.getByRole("banner")).not.toHaveTextContent("Unsaved changes"));
  });
});
