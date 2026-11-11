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

/** The new task page. It is not under /tasks/, so no task's name can clash with it. */
export const NEW_TASK = "/new-task";

export const LONGEST_NAME = 40;

/** Why a name cannot be a task's name, as the service checks it, or null. */
export function nameProblem(name: string): string | null {
  if (name === "") return "Give the task a name.";
  if (name !== name.trim()) return "A name has no space at either end.";
  if ([...name].length > LONGEST_NAME) return `A name is at most ${LONGEST_NAME} characters.`;
  if (name.includes("/")) return "A name cannot hold a /, because the task's address could not.";
  return null;
}

/** The task a page's address names, as in /tasks/:type/:name. */
export function routeTask(params: { type?: string; name?: string }): TaskRef {
  return { type: params.type ?? "", name: params.name ?? "" };
}
