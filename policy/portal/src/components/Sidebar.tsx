import { ChartColumn, ClipboardCheck, LogOut, PanelLeftClose, PanelLeftOpen, type LucideIcon } from "lucide-react";
import { useCallback, type KeyboardEvent, type PointerEvent } from "react";
import { NavLink, useNavigate } from "react-router";
import { signOut } from "../api";
import { useExpander } from "../motion";
import { KEY_STEP, useSidebar } from "../sidebar";

type Entry = { to: string; label: string; icon: LucideIcon };

// A new portal page adds its entry here and its route in routes.tsx.
export const ENTRIES: Entry[] = [
  { to: "/attempts", label: "Attempts", icon: ClipboardCheck },
  { to: "/usage", label: "Usage", icon: ChartColumn },
];

export function Sidebar({ username }: { username: string }) {
  const { width, limits, collapsed, resize, setCollapsed } = useSidebar();
  const setExpanded = useCallback((value: boolean) => setCollapsed(!value), [setCollapsed]);
  const { shown, moving, toggle: toggleSidebar } = useExpander(!collapsed, setExpanded);
  const navigate = useNavigate();

  async function leave() {
    await signOut();
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
              </ul>
            </nav>
          </>
        )}
        <div className="sidebar-bottom">
          {shown && (
            <p className="sidebar-user sidebar-fold" inert={collapsed}>
              Signed in as <strong>{username}</strong>
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
