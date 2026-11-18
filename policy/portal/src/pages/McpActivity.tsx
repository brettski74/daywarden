import { Link, useLoaderData, type LoaderFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { MCP, MCP_ACTIVITY_DATA, type McpActivity as Activity } from "../mcp";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { TITLE as MCP_TITLE } from "./Mcp";

const TITLE = "Activity";
const OUTCOMES: Record<string, string> = {
  approved: "Approved",
  revoked: "Revoked",
  lapsed: "Lapsed",
  refused: "Refused",
  done: "Done",
  failed: "Failed",
};

export async function mcpActivityLoader({ request }: LoaderFunctionArgs): Promise<Activity> {
  return api<Activity>(MCP_ACTIVITY_DATA, { page: pageOf(request), signal: request.signal });
}

/** The MCP activity log, newest first: each write, each refused call, and each connection approved, revoked, or lapsed. */
export function McpActivity() {
  const { entries, keep_days, times } = useLoaderData() as Activity;
  useTitle(`MCP ${TITLE}`);
  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Settings</li>
            <li>
              <Link to={MCP}>{MCP_TITLE}</Link>
            </li>
            <li>
              <h1 className="bar-title">{TITLE}</h1>
            </li>
          </ol>
        </nav>
      </ContextBar>

      {entries.length === 0 ? (
        <p>Nothing has happened yet. Reads that succeed are not listed.</p>
      ) : (
        <table className="records">
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">Agent</th>
              <th scope="col">Approved By</th>
              <th scope="col">Tool</th>
              <th scope="col">Names</th>
              <th scope="col">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={`${entry.at}-${index}`}>
                <td>{entry.at}</td>
                <td>{entry.agent}</td>
                <td>{entry.parent}</td>
                <td>{entry.tool && <code>{entry.tool}</code>}</td>
                <td>{entry.target}</td>
                <td>
                  <span className={entry.outcome === "refused" || entry.outcome === "failed" ? "problem" : undefined}>
                    {OUTCOMES[entry.outcome] ?? entry.outcome}
                  </span>
                  {entry.reasons.length > 0 && <span>: {entry.reasons.join(" ")}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <StatusBar>
        <span>
          {entries.length} entr{entries.length === 1 ? "y" : "ies"}, kept for {keep_days} days.
        </span>
        <span>{times}</span>
      </StatusBar>
    </>
  );
}
