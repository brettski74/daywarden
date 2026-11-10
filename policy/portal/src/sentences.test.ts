import { describe, expect, it } from "vitest";
import {
  NONE_SORTED,
  NO_NAME,
  NO_WORDS,
  blocked,
  blocksChanged,
  countsText,
  defaultRequired,
  loaded,
  ordinal,
  place,
  problems,
  recognized,
  retext,
  segments,
  splitWords,
  toRequest,
  unsort,
  warnings,
  type Block,
  type PosData,
} from "./sentences";

const DATA: PosData = {
  settings: { timeout: "45s", correct_answers_required: "" },
  sentences: [
    { text: "The cat sat on the mat.", timeout: "", parts: [{ name: "noun", words: [1, 5] }, { name: "verb", words: [2] }] },
    { text: "Dry the dishes with a dry towel.", timeout: "2m", parts: [{ name: "verb", words: [0] }, { name: "adjective", words: [5] }] },
  ],
  problems: [],
};

describe("splitting a sentence into words", () => {
  it("splits as the loader does, joining runs across an apostrophe or hyphen between letters", () => {
    expect(splitWords("Don\u2019t pull the dogs' well-known rope -- now, o'clock café 3rd.").map((word) => word.text)).toEqual([
      "Don\u2019t",
      "pull",
      "the",
      "dogs",
      "well-known",
      "rope",
      "now",
      "o'clock",
      "café",
      "3rd",
    ]);
  });

  it("counts the occurrences of a word ignoring case, with \u2019 the same as '", () => {
    expect(splitWords("Dry the dishes with a dry towel.").map((word) => [word.text, word.occurrence])).toEqual([
      ["Dry", 1],
      ["the", 1],
      ["dishes", 1],
      ["with", 1],
      ["a", 1],
      ["dry", 2],
      ["towel", 1],
    ]);
    expect(splitWords("It's it\u2019s").map((word) => word.occurrence)).toEqual([1, 2]);
  });

  it("keeps the text between words as it is", () => {
    expect(segments("Hi, you!")).toEqual([{ text: "Hi", word: 0 }, { text: ", " }, { text: "you", word: 1 }, { text: "!" }]);
  });
});

describe("editing a sentence's text", () => {
  it("keeps each sorted word still in the sentence in its row and names the rest", () => {
    const [cat] = loaded(DATA);
    const dog = retext(cat, "The dog sat on the mat.");
    expect(dog.rows.map((row) => row.words)).toEqual([[5], [2]]);
    expect(warnings(dog)).toEqual(["No longer in the sentence, so taken out of the table: cat."]);
    const moved = retext(dog, "On the big mat, the dog SAT.");
    expect(moved.rows.map((row) => row.words)).toEqual([[3], [6]]);
  });

  it("matches by which occurrence a word is, so taking out the second dry names only it", () => {
    const [, dry] = loaded(DATA);
    const shorter = retext({ ...dry, rows: [...dry.rows, { id: "x", origin: null, name: "noun", words: [2, 6] }] }, "Dry the dishes with a towel.");
    expect(shorter.rows.map((row) => row.words)).toEqual([[0], [], [2, 5]]);
    expect(shorter.removed).toEqual(["dry (2nd)"]);
  });

  it("says which ordinal an occurrence is", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 111].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "111th"]);
  });
});

describe("problems and warnings", () => {
  const block = (change: Partial<Block>): Block => ({ ...loaded(DATA)[0], ...change });

  it("finds a sentence with no words, a row with no name, and a sentence with nothing sorted", () => {
    expect(problems(block({}))).toEqual([]);
    expect(problems(block({ text: " ... ", rows: [] }))).toEqual([NO_WORDS]);
    expect(problems(block({ rows: [{ id: "a", origin: null, name: "  ", words: [1] }] }))).toEqual([NO_NAME]);
    expect(problems(block({ rows: [{ id: "a", origin: null, name: "noun", words: [] }] }))).toEqual([NONE_SORTED]);
    expect(blocked([])).toBe(true);
    expect(blocked(loaded(DATA))).toBe(false);
  });

  it("recognizes the listed parts of speech and their plurals, ignoring case and spaces at the ends", () => {
    expect(["Nouns", "VERB", "  proper nouns ", "interjection"].every(recognized)).toBe(true);
    expect(["Subject", "nounss", "proper  noun", ""].some(recognized)).toBe(false);
    expect(warnings(block({ rows: [{ id: "a", origin: null, name: "Subject", words: [1] }] }))).toEqual([
      '"Subject" is not a recognized part of speech.',
    ]);
  });

  it("counts the sentences and those with problems, and works out the default pass mark", () => {
    expect(countsText(loaded(DATA))).toBe("2 sentences. None with problems.");
    expect(countsText([block({ text: "" })])).toBe("1 sentence. 1 with problems.");
    expect([1, 2, 3, 5, 10].map(defaultRequired)).toEqual([1, 2, 3, 4, 7]);
  });
});

describe("what has changed", () => {
  it("sees nothing changed until a word, a name, a timeout, the text, or the list changes", () => {
    const blocks = loaded(DATA);
    expect(blocksChanged(DATA, blocks)).toBe(false);
    expect(blocksChanged(DATA, [place(blocks[0], 3, "s0r1"), blocks[1]])).toBe(true);
    expect(blocksChanged(DATA, [unsort(place(blocks[0], 3, "s0r1"), 3), blocks[1]])).toBe(false);
    expect(blocksChanged(DATA, [{ ...blocks[0], timeout: "1m" }, blocks[1]])).toBe(true);
    expect(blocksChanged(DATA, [blocks[0]])).toBe(true);
    expect(blocksChanged(DATA, [retext(blocks[0], "A cat sat on the mat."), blocks[1]])).toBe(true);
  });

  it("sends each sentence with its place in the file and its rows as typed", () => {
    expect(toRequest(loaded(DATA))[1]).toEqual({
      origin: 1,
      text: "Dry the dishes with a dry towel.",
      timeout: "2m",
      parts: [{ name: "verb", words: [0] }, { name: "adjective", words: [5] }],
    });
  });
});
