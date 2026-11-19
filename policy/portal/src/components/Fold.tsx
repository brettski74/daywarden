import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useExpander } from "../motion";

/** A section under a heading that starts closed unless told to open, and opens and closes with the shared animation from its heading's button. */
export function Fold({ title, children, open: startOpen = false, level = 2 }: { title: string; children: ReactNode; open?: boolean; level?: 2 | 3 | 4 }) {
  const [open, setOpen] = useState(startOpen);
  const Heading = `h${level}` as const;
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const heading = useId();
  const panel = useId();
  return (
    <section className="fold" aria-labelledby={heading} data-open={open || undefined} data-moving={moving || undefined}>
      <Heading className="fold-heading">
        <button type="button" className="fold-toggle" aria-expanded={open} aria-controls={panel} onClick={toggle}>
          <ChevronRight className="fold-chevron" aria-hidden="true" />
          <span id={heading}>{title}</span>
        </button>
      </Heading>
      {shown && (
        <div className="fold-panel" id={panel} inert={!open}>
          <div className="fold-body">{children}</div>
        </div>
      )}
    </section>
  );
}
