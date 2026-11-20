import { Check, X } from "lucide-react";
import { useState } from "react";
import { Link, useLoaderData, useLocation, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { MCP, MCP_CONNECT_DATA, classLabel, type McpRequest } from "../mcp";
import { useSession } from "../session";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { TITLE as MCP_TITLE } from "./Mcp";

const TITLE = "Connect an Agent";

export async function mcpConnectLoader({ request }: LoaderFunctionArgs): Promise<McpRequest> {
  const asked = new URL(request.url).searchParams.get("request") ?? "";
  return api<McpRequest>(`${MCP_CONNECT_DATA}?request=${encodeURIComponent(asked)}`, { page: pageOf(request), signal: request.signal });
}

/** Leave the portal for the agent's return address. The one place the portal sends the browser outside itself. */
export const browser = {
  leave(location: string): void {
    window.location.assign(location);
  },
};

/**
 * The consent page an agent opens. Nothing is approved by loading it: Approve
 * and Deny each wait for the parent, then send the browser to the agent's
 * return address, with a code or with access_denied.
 */
export function McpConnect() {
  const shown = useLoaderData() as McpRequest;
  const { pathname, search } = useLocation();
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  // The MCP page is for admins, so a reviewer's breadcrumb names it without linking to it.
  const admin = useSession().role === "admin";
  useTitle(TITLE);

  async function decide(decision: "approve" | "deny") {
    setBusy(true);
    try {
      const done = await api<{ location: string }>(MCP_CONNECT_DATA, {
        page: `/parent${pathname}${search}`,
        method: "POST",
        body: { request: shown.request, decision },
      });
      browser.leave(done.location);
    } catch (error) {
      setBusy(false);
      if (!(error instanceof ApiError)) throw error;
      setRefused(error.message);
    }
  }

  const problem = refused ?? shown.problem;
  const nothing = Boolean(shown.reviewer) && !shown.permissions?.length;
  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Settings</li>
            <li>{admin ? <Link to={MCP}>{MCP_TITLE}</Link> : MCP_TITLE}</li>
            <li>
              <h1 className="bar-title">{TITLE}</h1>
            </li>
          </ol>
        </nav>
      </ContextBar>

      <div className="mcp-consent">
        {shown.agent && (
          <dl className="mcp-consent-facts">
            <dt>Agent</dt>
            <dd>{shown.agent}</dd>
            <dt>Client ID</dt>
            <dd>
              <code>{shown.client_id}</code>
            </dd>
            {shown.redirect_uri && (
              <>
                <dt>Returns To</dt>
                <dd>
                  <code>{shown.redirect_uri}</code>
                </dd>
              </>
            )}
          </dl>
        )}
        {problem ? (
          <p className="note note-problem" role="alert">
            {problem}
          </p>
        ) : (
          <>
            <p>Approving lets this agent use the MCP server with these permissions, until the connection is revoked or lapses.</p>
            {shown.reviewer && <p>You are a reviewer, so an agent you approve can only read attempts and usage.</p>}
            {nothing ? (
              <p className="note note-problem">
                The MCP server gives agents no permission to read attempts or usage, so there is nothing a reviewer's agent could use.
                An admin can approve this agent instead.
              </p>
            ) : shown.permissions && shown.permissions.length > 0 ? (
              <ul className="mcp-consent-permissions">
                {shown.permissions.map(({ name, permissions }) => (
                  <li key={name}>
                    <span title={name}>{classLabel(name)}</span>: {permissions.join(", ")}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No permissions are granted now, so the agent would see no tools.</p>
            )}
            <div className="dialog-buttons mcp-consent-buttons">
              <button type="button" className="button button-quiet" onClick={() => decide("deny")} disabled={busy}>
                <X aria-hidden="true" />
                Deny
              </button>
              <button
                type="button"
                className="button"
                onClick={() => decide("approve")}
                disabled={busy || nothing}
                title={nothing ? "There is nothing a reviewer's agent could use." : undefined}
              >
                <Check aria-hidden="true" />
                Approve
              </button>
            </div>
          </>
        )}
      </div>

      <StatusBar>
        <span>{problem ? "This agent cannot be approved from here." : "Approve or Deny sends the browser back to the agent."}</span>
      </StatusBar>
    </>
  );
}
