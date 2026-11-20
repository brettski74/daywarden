import { redirect, type RouteObject } from "react-router";
import { Layout, layoutLoader } from "./components/Layout";
import { Attempt, attemptLoader } from "./pages/Attempt";
import { Attempts, attemptsAction, attemptsLoader } from "./pages/Attempts";
import { Facts, factsLoader, factsShouldRevalidate } from "./pages/Facts";
import { Login, loginLoader } from "./pages/Login";
import { Mcp, mcpAction, mcpLoader, mcpShouldRevalidate } from "./pages/Mcp";
import { McpActivity, mcpActivityLoader } from "./pages/McpActivity";
import { McpConnect, mcpConnectLoader } from "./pages/McpConnect";
import { RuleSetPage, RuleSetsPage } from "./pages/RuleSets";
import { HouseholdPage, ItemsPage, policyAction, policyLoader, policyShouldRevalidate } from "./pages/Policy";
import { Pool, poolAction, poolLoader, poolShouldRevalidate } from "./pages/Pool";
import { Pools, poolsLoader } from "./pages/Pools";
import { NotFound, PageError, ShellError } from "./pages/Problems";
import { NewTask, Task, newTaskAction, newTaskLoader, taskAction, taskLoader, taskShouldRevalidate } from "./pages/Task";
import { Requests, requestsLoader } from "./pages/Requests";
import { TaskTrend, trendLoader, trendShouldRevalidate } from "./pages/TaskTrend";
import { Usage, usageLoader } from "./pages/Usage";
import { Words, wordsLoader, wordsShouldRevalidate } from "./pages/Words";
import type { PageKey } from "./policy";
import { Week, oldWeekLoader, weekAction, weekLoader } from "./pages/Week";
import { adminOnly } from "./session";

export const BASENAME = "/parent";

/** The policy pages, each loading and saving its whole section at /parent/api/policy/<page>. */
function policyRoutes(): RouteObject[] {
  const common = (key: PageKey) => ({ path: `policy/${key}`, loader: policyLoader(key), action: policyAction(key), shouldRevalidate: policyShouldRevalidate });
  return [
    ...(["client-groups", "site-groups", "time-windows", "quotas"] as const).map((key) => ({ ...common(key), element: <ItemsPage key={key} page={key} /> })),
    { ...common("rule-sets"), element: <RuleSetsPage key="list" /> },
    { ...common("rule-sets"), path: "policy/rule-sets/:name", element: <RuleSetPage /> },
    { ...common("household"), element: <HouseholdPage key="household" /> },
  ];
}

const loading = <div className="loading" aria-busy="true" />;

// A new portal page adds its route under the layout and its entry in the sidebar. It is an admin page, wrapped in
// adminOnly, unless it fits the reviewer rule in Access control in docs/parent-portal.md.
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
          { path: "attempts/tasks/:type/:name", element: <TaskTrend />, loader: trendLoader, shouldRevalidate: trendShouldRevalidate },
          { path: "attempts/facts/:operation", element: <Facts />, loader: factsLoader, shouldRevalidate: factsShouldRevalidate },
          { path: "attempts/words", element: <Words />, loader: wordsLoader, shouldRevalidate: wordsShouldRevalidate },
          { path: "attempts/:id", element: <Attempt />, loader: attemptLoader },
          { path: "usage", loader: () => redirect("/usage/minutes") },
          { path: "usage/minutes", element: <Usage unit="minutes" />, loader: usageLoader("minutes") },
          { path: "usage/bytes", element: <Usage unit="bytes" />, loader: usageLoader("bytes") },
          { path: "usage/requests", element: <Requests />, loader: requestsLoader },
          ...[
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
            { path: "assets/parts-of-speech-pools", element: <Pools />, loader: poolsLoader },
            {
              path: "assets/parts-of-speech-pools/:id",
              element: <Pool />,
              loader: poolLoader,
              action: poolAction,
              shouldRevalidate: poolShouldRevalidate,
            },
            { path: "assets/capitalisation-pools", element: <Pools />, loader: poolsLoader },
            {
              path: "assets/capitalisation-pools/:id",
              element: <Pool />,
              loader: poolLoader,
              action: poolAction,
              shouldRevalidate: poolShouldRevalidate,
            },
            ...policyRoutes(),
            { path: "settings/mcp", element: <Mcp />, loader: mcpLoader, action: mcpAction, shouldRevalidate: mcpShouldRevalidate },
            { path: "settings/mcp/activity", element: <McpActivity />, loader: mcpActivityLoader },
          ].map(adminOnly),
          // The consent page is open to reviewers: their agent is limited to what a reviewer may read.
          { path: "settings/mcp/connect", element: <McpConnect />, loader: mcpConnectLoader },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
