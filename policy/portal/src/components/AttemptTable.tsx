import { Link } from "react-router";
import type { AttemptRow } from "../attempts";

/** Attempts newest first, each opening its own page. The attempts page and a task's trend list them alike. */
export function AttemptTable({ rows, label }: { rows: AttemptRow[]; label: string }) {
  return (
    <table className="records" aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Task</th>
          <th scope="col">Type</th>
          <th scope="col">Set</th>
          <th scope="col">Started</th>
          <th scope="col">Finished</th>
          <th scope="col">Outcome</th>
          <th scope="col">Duration</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>
              <Link to={`/attempts/${row.id}`}>{row.task}</Link>
            </td>
            <td>{row.type}</td>
            <td>{row.set}</td>
            <td>{row.started}</td>
            <td>{row.finished}</td>
            <td>{row.outcome}</td>
            <td>{row.duration}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
