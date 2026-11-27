import { FileDiff as FileChanged, FileMinus, FilePlus, type LucideIcon } from "lucide-react";
import { STATUS_LABELS, type FileDiff } from "../configHistory";

const ICONS: Record<FileDiff["status"], LucideIcon> = { added: FilePlus, changed: FileChanged, removed: FileMinus };
const SIGNS: Record<string, string> = { "+": "+", "-": "-", " ": "" };
const LINE_LABELS: Record<string, string> = { "+": "added", "-": "removed", " ": "unchanged" };

/**
 * Each file that differs, marked added, changed, or removed, with each changed part and three lines of context.
 *
 * Added and removed lines carry + and - as well as their colours, which are the theme's --diff-* role properties.
 */
export function DiffView({ files, empty = "Nothing differs." }: { files: FileDiff[]; empty?: string }) {
  if (files.length === 0) return <p className="diff-empty">{empty}</p>;
  return (
    <div className="diff">
      {files.map((file) => (
        <FileSection key={file.path} file={file} />
      ))}
    </div>
  );
}

function FileSection({ file }: { file: FileDiff }) {
  const Icon = ICONS[file.status];
  return (
    <section className="diff-file" data-status={file.status} aria-label={`${file.path}, ${file.status}`}>
      <h3 className="diff-file-head">
        <Icon aria-hidden="true" />
        <code>{file.path}</code>
        <span className="diff-status">{STATUS_LABELS[file.status]}</span>
      </h3>
      {file.binary ? (
        <p className="note">This file is not text, so its changes are not shown.</p>
      ) : (
        <div className="diff-scroll">
          <table className="diff-lines">
            {file.hunks.map((hunk, index) => (
              <tbody key={index}>
                <tr className="diff-hunk">
                  <td colSpan={4}>
                    <code>{hunk.header}</code>
                  </td>
                </tr>
                {hunk.lines.map((line, number) => (
                  <tr key={number} className="diff-line" data-kind={LINE_LABELS[line.kind]}>
                    <td className="diff-number">{line.old ?? ""}</td>
                    <td className="diff-number">{line.new ?? ""}</td>
                    <td className="diff-sign" aria-label={LINE_LABELS[line.kind]}>
                      {SIGNS[line.kind]}
                    </td>
                    <td className="diff-text">
                      <code>{line.text}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </section>
  );
}
