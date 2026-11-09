export type Stored = string | number | boolean | null | Stored[] | { [key: string]: Stored };

/** Lay out a value from a stored attempt record: text, a numbered list, or labelled fields. */
export function StoredValue({ value }: { value: Stored }) {
  if (value === null) return null;
  if (typeof value === "boolean") return <>{value ? "true" : "false"}</>;
  if (typeof value === "string" || typeof value === "number") return <>{String(value)}</>;
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    return (
      <ol>
        {value.map((item, index) => (
          <li key={index}>
            <StoredValue value={item} />
          </li>
        ))}
      </ol>
    );
  }
  return <Fields value={value} />;
}

export function Fields({ value }: { value: { [key: string]: Stored } }) {
  return (
    <dl className="fields">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>
            <StoredValue value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
