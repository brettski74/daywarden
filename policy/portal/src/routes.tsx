import { redirect, type RouteObject } from "react-router";
import { Layout, layoutLoader } from "./components/Layout";
import { Attempt, attemptLoader } from "./pages/Attempt";
import { Attempts, attemptsAction, attemptsLoader } from "./pages/Attempts";
import { Login, loginLoader } from "./pages/Login";
import { NotFound, PageError, ShellError } from "./pages/Problems";
import { NewTask, Task, newTaskAction, newTaskLoader, taskAction, taskLoader, taskShouldRevalidate } from "./pages/Task";
import { Usage, usageLoader } from "./pages/Usage";
import { Week, oldWeekLoader, weekAction, weekLoader } from "./pages/Week";

export const BASENAME = "/parent";

const loading = <div className="loading" aria-busy="true" />;

// A new portal page adds its route under the layout and its entry in the sidebar.
export const routes: RouteObject[] = [
  { path: "/login", element: <Login />, loader: loginLoader, errorElement: <ShellError />, hydrateFallbackElement: loading },
  {
    path: "/",
    element: <Layout />,
    loader: layoutLoader,
    errorElement: <ShellError />,
    hydrateFallbackElement: loading,
    children: [
      {
        errorElement: <PageError />,
        children: [
          { index: true, loader: () => redirect("/attempts") },
          { path: "attempts", element: <Attempts />, loader: attemptsLoader, action: attemptsAction },
          { path: "attempts/:id", element: <Attempt />, loader: attemptLoader },
          { path: "usage", element: <Usage />, loader: usageLoader },
          {
            path: "tasks/:type/:name",
            element: <Task />,
            loader: taskLoader,
            action: taskAction,
            shouldRevalidate: taskShouldRevalidate,
          },
          { path: "tasks/:type/:name/words/:mode", element: <Week />, loader: weekLoader, action: weekAction },
          { path: "tasks/:type/:name/week", loader: oldWeekLoader },
          { path: "new-task", element: <NewTask />, loader: newTaskLoader, action: newTaskAction },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
