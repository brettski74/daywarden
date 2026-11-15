import { Link, useNavigate } from "react-router";
import type { RequestRow } from "../usage";

const COLUMNS: { key: string; label: string }[] = [
  { key: "start", label: "Start" },
  { key: "end", label: "End" },
  { key: "duration", label: "Duration" },
  { key: "address", label: "Address" },
  { key: "client", label: "Client group" },
  { key: "site", label: "Site group" },
  { key: "quotas", label: "Quotas" },
  { key: "method", label: "Method" },
  { key: "host", label: "Host" },
  { key: "path", label: "Path" },
  { key: "query", label: "Query" },
  { key: "status", label: "Status" },
  { key: "type", label: "Type" },
  { key: "down", label: "Down" },
  { key: "up", label: "Up" },
  { key: "outcome", label: "Outcome" },
];

const FIELDS: Record<string, keyof RequestRow> = {
  start: "start",
  end: "end",
  duration: "duration",
  address: "address",
  client: "client_group",
  site: "site_group",
  quotas: "quotas",
  method: "method",
  host: "host",
  path: "path",
  query: "query",
  status: "status",
  type: "type",
  down: "down",
  up: "up",
  outcome: "outcome",
};

type Props = {
  rows: RequestRow[];
  sort: string;
  dir: "asc" | "desc";
  page: number;
  pages: number;
  /** Build the address for a sort or page change. */
  href: (patch: { sort?: string; dir?: "asc" | "desc"; page?: number }) => string;
  /** Said in the one empty row when there are no requests. */
  empty?: string;
};

/** The shared request table: sortable headings, sticky headers, and Previous/Next page links. */
export function RequestTable({ rows, sort, dir, page, pages, href, empty = "No requests in this range." }: Props) {
  const navigate = useNavigate();

  function sortTo(key: string): string {
    if (sort === key) return href({ sort: key, dir: dir === "asc" ? "desc" : "asc", page: 1 });
    return href({ sort: key, dir: "asc", page: 1 });
  }

  return (
    <div className="request-table">
      <table className="records">
        <thead>
          <tr>
            {COLUMNS.map(({ key, label }) => {
              const active = sort === key;
              const arrow = active ? (dir === "asc" ? " ↑" : " ↓") : "";
              return (
                <th key={key} scope="col" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
                  <button type="button" className="records-sort" onClick={() => navigate(sortTo(key))}>
                    <span className="records-sort-label">{label}</span>
                    {arrow && <span className="records-sort-arrow" aria-hidden="true">{arrow}</span>}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length}>{empty}</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.id}>
                {COLUMNS.map(({ key }) => {
                  const field = FIELDS[key];
                  const value = row[field];
                  if (key === "path") {
                    return (
                      <td key={key} title={row.url}>
                        {value}
                      </td>
                    );
                  }
                  return <td key={key}>{value}</td>;
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {pages > 1 && (
        <nav className="request-pages" aria-label="Request pages">
          {page > 1 ? (
            <Link to={href({ page: page - 1 })}>Previous</Link>
          ) : (
            <span className="request-pages-disabled">Previous</span>
          )}
          {page < pages ? <Link to={href({ page: page + 1 })}>Next</Link> : <span className="request-pages-disabled">Next</span>}
        </nav>
      )}
    </div>
  );
}
