/**
 * The advice under a new password that says which of the household's rules it
 * breaks and how to fix it (S046), one line for each rule. It says nothing
 * when every rule passes.
 */
export function RuleAdvice({ id, problems }: { id: string; problems: string[] }) {
  return (
    <div id={id} className="rule-advice" aria-live="polite">
      {problems.map((problem) => (
        <p key={problem}>{problem}</p>
      ))}
    </div>
  );
}
