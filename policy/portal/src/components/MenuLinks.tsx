import { ChevronDown, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Link } from "react-router";
import { useExpander } from "../motion";

export type MenuLink = { label: string; to: string };

type Props = {
  label: string;
  icon: LucideIcon;
  links: MenuLink[];
  /** Called on a plain click of a link before it is followed. It may call ``preventDefault`` to stay. */
  onFollow?: (event: MouseEvent<HTMLAnchorElement>, link: MenuLink) => void;
};

/**
 * A context bar button that opens a menu of links.
 *
 * Each entry is a real link, so a middle click and Copy link address work.
 * The arrow keys move between them, Enter follows one, and Escape or a
 * click elsewhere closes the menu.
 */
export function MenuLinks({ label, icon: Icon, links, onFollow }: Props) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLAnchorElement | null)[]>([]);
  const menuId = useId();

  const close = useCallback(
    (refocus: boolean) => {
      if (!open) return;
      toggle();
      if (refocus) button.current?.focus();
    },
    [open, toggle],
  );

  useEffect(() => {
    if (!open) return;
    items.current[0]?.focus();
    function away(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) close(false);
    }
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, close]);

  function key(event: KeyboardEvent<HTMLUListElement>) {
    const at = items.current.findIndex((item) => item === document.activeElement);
    const last = links.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(at + 1, last),
      ArrowUp: Math.max(at - 1, 0),
      Home: 0,
      End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      items.current[moves[event.key]]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <div className="menu-links" ref={root} data-open={open || undefined} data-moving={moving || undefined}>
      <button
        type="button"
        ref={button}
        className="button button-quiet"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={toggle}
      >
        <Icon aria-hidden="true" />
        {label}
        <ChevronDown className="menu-links-chevron" aria-hidden="true" />
      </button>
      {shown && (
        <div className="menu-links-panel" inert={!open}>
          <ul id={menuId} role="menu" aria-label={label} onKeyDown={key}>
            {links.map((link, index) => (
              <li key={link.to} role="none">
                <Link
                  role="menuitem"
                  to={link.to}
                  ref={(element) => {
                    items.current[index] = element;
                  }}
                  onClick={(event) => {
                    const plain = event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
                    if (plain) onFollow?.(event, link);
                    close(false);
                  }}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
