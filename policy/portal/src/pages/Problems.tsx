import { Link, isRouteErrorResponse, useRouteError } from "react-router";
import { ApiError } from "../api";
import { ContextBar, useTitle } from "../slots";

export function NotFound() {
  useTitle("Not found");
  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Not found</h1>
      </ContextBar>
      <p>There is no portal page at this address.</p>
      <p>
        <Link to="/">Go to the portal home</Link>
      </p>
    </>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`;
  return "The service did not answer. Check that Daywarden is running, then reload the page.";
}

/** A page whose data could not be loaded, shown in the content pane with the layout around it. */
export function PageError() {
  useTitle("Problem");
  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Problem</h1>
      </ContextBar>
      <p>{describe(useRouteError())}</p>
    </>
  );
}

/** The portal could not open at all, such as when the service is down. */
export function ShellError() {
  useTitle("Problem");
  return (
    <div className="signin">
      <div className="signin-panel">
        <div className="signin-logo" role="img" aria-label="Daywarden" />
        <h1>Parent portal</h1>
        <p>{describe(useRouteError())}</p>
      </div>
    </div>
  );
}
