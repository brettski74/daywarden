import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useExpander } from "../motion";

/** A section under a heading that starts closed, and opens and closes with the shared animation from its heading's button. */
export function Fold({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const heading = useId();
  const panel = useId();
  return (
    <section className="fold" aria-labelledby={heading} data-open={open || undefined} data-moving={moving || undefined}>
      <h2 className="fold-heading">
        <button type="button" className="fold-toggle" aria-expanded={open} aria-controls={panel} onClick={toggle}>
          <ChevronRight className="fold-chevron" aria-hidden="true" />
          <span id={heading}>{title}</span>
        </button>
      </h2>
      {shown && (
        <div className="fold-panel" id={panel} inert={!open}>
          <div className="fold-body">{children}</div>
        </div>
      )}
    </section>
  );
}
