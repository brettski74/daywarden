// The drag-and-drop the parts of speech editor shares with the child's quiz page. It lives outside the
// portal, in policy/static, because the child's page inlines the same file.
export { PRESS_THRESHOLD, sortModel, wordSort } from "../../static/word_sort.js";
export type { Cells, DropTarget, WordSort, WordSortOptions } from "../../static/word_sort.js";
