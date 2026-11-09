import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { BASENAME, routes } from "./routes";
import "./styles/layout.css";
import "./styles/theme.css";

const router = createBrowserRouter(routes, { basename: BASENAME });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
