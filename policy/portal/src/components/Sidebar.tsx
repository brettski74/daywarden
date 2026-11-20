import {
  ChartColumn,
  ChevronRight,
  ClipboardCheck,
  Library,
  ListChecks,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldCheck,
  SquarePlus,
  type LucideIcon,
} from "lucide-react";
import { useCallback, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { signOut } from "../api";
import { forgetSession, type Session } from "../session";
import { useExpander } from "../motion";
import { CAPITALISATION_POOLS, PARTS_POOLS } from "../pools";
import { MCP } from "../mcp";
import { ASSETS_KEY, KEY_STEP, POLICY_KEY, SETTINGS_KEY, TASKS_KEY, USAGE_KEY, useGroupList, useSidebar } from "../sidebar";
import { POLICY, POLICY_PAGES, policyPath } from "../policy";
import { NEW_TASK, taskLabel, taskPath, type TaskRef } from "../taskRef";

type Entry = { to: string; label: string; icon: LucideIcon };

// A new portal page adds its entry here, or in a group below, and its route in routes.tsx.
export const ENTRIES: Entry[] = [{ to: "/attempts", label: "Attempts", icon: ClipboardCheck }];

const USAGE_PAGES = ["/usage/minutes", "/usage/bytes", "/usage/requests"];

/** A button that expands a list of links, indented beneath it. It stays expanded while one of its pages is open. */
function NavGroup({ id, label, icon: Icon, storageKey, onItsPage, hint, children }: {
  id: string;
  label: string;
  icon: LucideIcon;
  storageKey: string;
  onItsPage: boolean;
  /** The button's title while one of the group's pages is open. */
  hint: string;
  children: ReactNode;
}) {
  const { expanded, setExpanded } = useGroupList(storageKey, onItsPage);
  const { shown, moving, toggle } = useExpander(expanded, setExpanded);
  return (
    <li className="nav-group" data-open={expanded || undefined} data-moving={moving || undefined}>
      <button
        type="button"
        className="nav-group-toggle"
        aria-expanded={expanded}
        aria-controls={id}
        aria-disabled={onItsPage || undefined}
        title={onItsPage ? hint : undefined}
        onClick={onItsPage ? undefined : toggle}
      >
        <Icon aria-hidden="true" />
        <span>{label}</span>
        <ChevronRight className="nav-chevron" aria-hidden="true" />
      </button>
      {shown && (
        <div className="nav-sub" inert={!expanded}>
          <ul id={id}>{children}</ul>
        </div>
      )}
    </li>
  );
}

/** Usage: Minutes, Bytes, and Requests. Moving between them keeps the settings in the address. */
function UsageGroup() {
  const { pathname, search } = useLocation();
  const onUsagePage = USAGE_PAGES.includes(pathname);
  const kept = onUsagePage ? search : "";
  return (
    <NavGroup id="usage-list" label="Usage" icon={ChartColumn} storageKey={USAGE_KEY} onItsPage={onUsagePage} hint="The usage list stays open while a usage page is open">
      <li>
        <NavLink to={{ pathname: "/usage/minutes", search: kept }}>Minutes</NavLink>
      </li>
      <li>
        <NavLink to={{ pathname: "/usage/bytes", search: kept }}>Bytes</NavLink>
      </li>
      <li>
        <NavLink to={{ pathname: "/usage/requests", search: kept }}>Requests</NavLink>
      </li>
    </NavGroup>
  );
}

/** Task Administration: the list of tasks, each a link to its page. */
function TaskGroup({ tasks }: { tasks: TaskRef[] }) {
  const { pathname } = useLocation();
  const onTaskPage = pathname.startsWith("/tasks/") || pathname === NEW_TASK;
  return (
    <NavGroup id="task-list" label="Task Administration" icon={ListChecks} storageKey={TASKS_KEY} onItsPage={onTaskPage} hint="The task list stays open while a task page is open">
      <li>
        <NavLink to={NEW_TASK} className="nav-new">
          <SquarePlus aria-hidden="true" />
          <span>Create New Task</span>
        </NavLink>
      </li>
      {tasks.map((task) => (
        <li key={`${task.type}/${task.name}`}>
          <NavLink to={taskPath(task)}>{taskLabel(task, tasks)}</NavLink>
        </li>
      ))}
    </NavGroup>
  );
}

/** Asset Administration: what tasks draw on, such as the parts of speech pools. */
function AssetGroup() {
  const { pathname } = useLocation();
  const onAssetPage = [PARTS_POOLS, CAPITALISATION_POOLS].some(({ list }) => pathname === list || pathname.startsWith(`${list}/`));
  return (
    <NavGroup id="asset-list" label="Asset Administration" icon={Library} storageKey={ASSETS_KEY} onItsPage={onAssetPage} hint="The asset list stays open while an asset page is open">
      <li>
        <NavLink to={CAPITALISATION_POOLS.list}>{CAPITALISATION_POOLS.title}</NavLink>
      </li>
      <li>
        <NavLink to={PARTS_POOLS.list}>{PARTS_POOLS.title}</NavLink>
      </li>
    </NavGroup>
  );
}

/** Policy: the household's groups, windows, quotas, and settings. */
function PolicyGroup() {
  const { pathname } = useLocation();
  const onPolicyPage = pathname.startsWith(`${POLICY}/`);
  return (
    <NavGroup id="policy-list" label="Policy" icon={ShieldCheck} storageKey={POLICY_KEY} onItsPage={onPolicyPage} hint="The policy list stays open while a policy page is open">
      {POLICY_PAGES.map((page) => (
        <li key={page.key}>
          <NavLink to={policyPath(page.key)}>{page.title}</NavLink>
        </li>
      ))}
    </NavGroup>
  );
}

/** Settings: the MCP server. */
function SettingsGroup() {
  const { pathname } = useLocation();
  const onSettingsPage = pathname === MCP || pathname.startsWith(`${MCP}/`);
  return (
    <NavGroup id="settings-list" label="Settings" icon={Settings} storageKey={SETTINGS_KEY} onItsPage={onSettingsPage} hint="The settings list stays open while a settings page is open">
      <li>
        <NavLink to={MCP}>MCP Server</NavLink>
      </li>
    </NavGroup>
  );
}

export function Sidebar({ session, tasks }: { session: Session; tasks: TaskRef[] }) {
  const { width, limits, collapsed, resize, setCollapsed } = useSidebar();
  const setExpanded = useCallback((value: boolean) => setCollapsed(!value), [setCollapsed]);
  const { shown, moving, toggle: toggleSidebar } = useExpander(!collapsed, setExpanded);
  const navigate = useNavigate();

  async function leave() {
    await signOut();
    forgetSession();
    navigate("/login", { replace: true });
  }

  function drag(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) resize(event.clientX, false);
  }

  function drop(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    resize(event.clientX);
  }

  function step(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = {
      ArrowLeft: width - KEY_STEP,
      ArrowRight: width + KEY_STEP,
      Home: limits.min,
      End: limits.max,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    resize(moves[event.key]);
  }

  const toggle = collapsed ? "Expand sidebar" : "Collapse sidebar";
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <aside
      className="sidebar"
      data-collapsed={collapsed || undefined}
      data-strip={!shown || undefined}
      data-moving={moving || undefined}
      style={{ width: collapsed ? undefined : `${width}px` }}
      aria-label="Portal"
    >
      <div className="sidebar-inner">
        <div className="sidebar-top">
          <button type="button" className="icon-button" onClick={toggleSidebar} aria-label={toggle} title={toggle} aria-expanded={!collapsed}>
            <ToggleIcon aria-hidden="true" />
          </button>
        </div>
        {shown && (
          <>
            <div className="sidebar-logo sidebar-fold" role="img" aria-label="Daywarden" inert={collapsed} />
            <nav className="sidebar-nav sidebar-fold" aria-label="Portal pages" inert={collapsed}>
              <ul>
                {ENTRIES.map(({ to, label, icon: Icon }) => (
                  <li key={to}>
                    <NavLink to={to}>
                      <Icon aria-hidden="true" />
                      <span>{label}</span>
                    </NavLink>
                  </li>
                ))}
                <UsageGroup />
                {/* A reviewer's sidebar is Attempts and Usage. Everything else is for admins. */}
                {session.role === "admin" && (
                  <>
                    <TaskGroup tasks={tasks} />
                    <AssetGroup />
                    <PolicyGroup />
                    <SettingsGroup />
                  </>
                )}
              </ul>
            </nav>
          </>
        )}
        <div className="sidebar-bottom">
          {shown && (
            <p className="sidebar-user sidebar-fold" inert={collapsed}>
              Signed in as <strong>{session.username}</strong> ({session.role})
            </p>
          )}
          <button type="button" className="sign-out" onClick={leave} aria-label="Sign out" title="Sign out">
            <LogOut aria-hidden="true" />
            {shown && <span className="sidebar-fold">Sign out</span>}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div
          className="sidebar-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          aria-valuenow={width}
          aria-valuemin={Math.round(limits.min)}
          aria-valuemax={Math.round(limits.max)}
          tabIndex={0}
          title="Drag, or use the left and right arrow keys, to resize the sidebar"
          onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
          onPointerMove={drag}
          onPointerUp={drop}
          onPointerCancel={drop}
          onKeyDown={step}
        />
      )}
    </aside>
  );
}
