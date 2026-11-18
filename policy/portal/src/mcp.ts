/** The MCP Server settings pages: their addresses, their data, and the edits the page makes before a save. */

/** The MCP page, under the router's /parent base. */
export const MCP = "/settings/mcp";
export const MCP_ACTIVITY = "/settings/mcp/activity";
export const MCP_CONNECT = "/settings/mcp/connect";
/** The data, under /parent/api. */
export const MCP_DATA = "/settings/mcp";
export const MCP_ACTIVITY_DATA = "/settings/mcp/activity";
export const MCP_CONNECT_DATA = "/settings/mcp/connect";

export const PERMISSIONS = ["create", "read", "update", "delete"] as const;
export const DURATIONS = ["access_token", "refresh_idle", "refresh_lifetime"] as const;
export type Duration = (typeof DURATIONS)[number];

export type McpSettings = {
  enabled: boolean;
  access_token: string;
  refresh_idle: string;
  refresh_lifetime: string;
  activity_days: number;
  permissions: Record<string, string[]>;
};

export type McpConnection = { id: number; agent: string; parent: string; approved: string; last_used: string; lapses: string };

export type McpPage = {
  exists: boolean;
  on: boolean;
  problems: string[];
  version: string;
  file: string;
  endpoint: string;
  settings: McpSettings;
  classes: { name: string; permissions: string[] }[];
  connections: McpConnection[];
};

export type McpActivity = {
  entries: { at: string; agent: string; parent: string; tool: string; target: string; outcome: string; reasons: string[] }[];
  keep_days: number;
  times: string;
};

export type McpRequest = {
  request?: string;
  agent?: string;
  client_id?: string;
  redirect_uri?: string;
  permissions?: { name: string; permissions: string[] }[];
  problem: string | null;
};

/** What the page calls each class. The class's own name, which mcp.yaml writes, is the title. */
export const CLASS_LABELS: Record<string, string> = {
  household: "Household",
  client_groups: "Client Groups",
  site_groups: "Site Groups",
  time_windows: "Time Windows",
  quotas: "Quotas",
  rule_sets: "Rule Sets",
  tasks: "Tasks",
  sentence_pools: "Sentence Pools",
  attempts: "Attempts",
  usage: "Usage",
};

export const DURATION_LABELS: Record<Duration | "activity_days", string> = {
  access_token: "Access Token Lasts",
  refresh_idle: "Connection Lapses When Unused For",
  refresh_lifetime: "Connection Lapses After Approval",
  activity_days: "Activity Kept For (Days)",
};

export function classLabel(name: string): string {
  return CLASS_LABELS[name] ?? name;
}

/** Whether a class is granted a permission. */
export function granted(settings: McpSettings, kind: string, permission: string): boolean {
  return (settings.permissions[kind] ?? []).includes(permission);
}

/** Return settings with one permission of one class turned on or off, in the order mcp.yaml writes them. */
export function withPermission(settings: McpSettings, kind: string, permission: string, on: boolean): McpSettings {
  const held = new Set(settings.permissions[kind] ?? []);
  if (on) held.add(permission);
  else held.delete(permission);
  return { ...settings, permissions: { ...settings.permissions, [kind]: PERMISSIONS.filter((name) => held.has(name)) } };
}

/** Why a duration cannot be saved, or null. The service checks it again. */
export function durationProblem(text: string): string | null {
  const match = /^([0-9]+)([mhd])$/.exec(text.trim());
  if (match && Number(match[1]) > 0) return null;
  return "Use a whole number above 0 with m, h, or d, such as 1h or 30d.";
}

export function daysProblem(text: string): string | null {
  return /^[0-9]+$/.test(text.trim()) && Number(text) > 0 ? null : "Use a whole number of days above 0.";
}

function samePermissions(a: McpSettings, b: McpSettings): boolean {
  const kinds = new Set([...Object.keys(a.permissions), ...Object.keys(b.permissions)]);
  return [...kinds].every((kind) => PERMISSIONS.every((name) => granted(a, kind, name) === granted(b, kind, name)));
}

/** Whether the page's settings differ from what was loaded. */
export function settingsChanged(saved: McpSettings, edited: McpSettings): boolean {
  return (
    saved.enabled !== edited.enabled ||
    DURATIONS.some((name) => saved[name].trim() !== edited[name].trim()) ||
    saved.activity_days !== edited.activity_days ||
    !samePermissions(saved, edited)
  );
}

/** Each permission on the page in the order it lists them, such as "tasks: create, read". */
export function grantedText(permissions: { name: string; permissions: string[] }[]): string[] {
  return permissions.map(({ name, permissions: names }) => `${classLabel(name)}: ${names.join(", ")}`);
}
