/** A task is named by its type and its name together. */
export type TaskRef = { type: string; name: string };

/** The address of a task's page under the portal, which is also where its data is under /parent/api. */
export function taskPath(task: TaskRef): string {
  return `/tasks/${encodeURIComponent(task.type)}/${encodeURIComponent(task.name)}`;
}

/** The task's name, with its type when another task in the list has the same name. */
export function taskLabel(task: TaskRef, tasks: TaskRef[]): string {
  return tasks.some((other) => other.name === task.name && other.type !== task.type) ? `${task.name} (${task.type})` : task.name;
}

/** The task a page's address names, as in /tasks/:type/:name. */
export function routeTask(params: { type?: string; name?: string }): TaskRef {
  return { type: params.type ?? "", name: params.name ?? "" };
}
