/** What the task pages call each policy file field. The field's own name is the label's title, to match the errors. */
export const LABELS: Record<string, string> = {
  name: "Name",
  type: "Type",
  pass_cooldown: "Pass Cooldown",
  failure_cooldown: "Failure Cooldown",
  max_skips: "Max Skips",
  max_passes: "Max Passes",
  available_from: "Available From",
  due_date: "Due Date",
  timeout: "Timeout",
  maximum_replays: "Maximum Replays",
  maximum_sentence_plays: "Maximum Sentence Plays",
  current_required: "Required Correct (Current Pool)",
  revision_required: "Required Correct (Revision Pool)",
  letter_pause: "Letter Pause",
  word_pause: "Word Pause",
  correct_answers_required: "Correct Answers Required",
  current_dir: "Current Pool Directory",
  revision_dir: "Revision Pool Directory",
  attic_dir: "Attic Directory",
  alphabet_dir: "Alphabet Directory",
  sequence_length: "Sequence Length",
  completed: "Completed",
  minimum_value: "Minimum Value",
  maximum_value: "Maximum Value",
  consecutive: "Consecutive",
  multiples_only: "Multiples Only",
  minimum_questions: "Minimum Questions",
  maximum_questions: "Maximum Questions",
  operation: "Operation",
  max_timeout: "Max Timeout",
  min_timeout: "Min Timeout",
};

export function label(field: string): string {
  return LABELS[field] ?? field;
}
