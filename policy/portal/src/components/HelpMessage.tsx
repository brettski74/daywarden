import { Link } from "react-router";
import { withinPortal } from "../api";

/** A message from the service whose last words, link, open a help page, such as "Your password was not changed. Learn more". */
export type Helped = { message: string; link?: string; help?: string };

export function HelpMessage({ message, link, help }: Helped) {
  if (!link || !help || !message.endsWith(link)) return <>{message}</>;
  return (
    <>
      {message.slice(0, message.length - link.length)}
      <Link to={withinPortal(help)}>{link}</Link>
    </>
  );
}
