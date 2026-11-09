import { useLoaderData, useSearchParams, type LoaderFunctionArgs } from "react-router";
import { api, pageOf } from "../api";
import { ContextBar, StatusBar, useTitle } from "../slots";

const KEYS = ["view", "client", "site", "quota"] as const;
type Key = (typeof KEYS)[number];

type BucketRow = { when: string; time: string; bytes: string; site?: string };
type Day = { heading: string; summary: string | null; rows: BucketRow[] };
type DaysReport = { kind: "days"; heading: string; note: string; site_column: boolean; days: Day[] };
type QuotaReport = { kind: "quota"; heading: string; day: string; limits: string[]; lines: string[] };
type BalancesReport = {
  kind: "balances";
  heading: string;
  day: string;
  limits: string[];
  rows: { client: string; time: string; bytes: string }[];
  empty: string;
};
type UsageData = {
  times: string;
  choices: { clients: string[]; sites: string[]; quotas: string[] };
  chosen: Record<Key, string>;
  report: DaysReport | QuotaReport | BalancesReport | null;
  message: string | null;
};

export async function usageLoader({ request }: LoaderFunctionArgs): Promise<UsageData> {
  const asked = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of KEYS) {
    const value = asked.get(key);
    if (value) query.set(key, value);
  }
  const search = query.toString();
  return api<UsageData>(`/usage${search ? `?${search}` : ""}`, { page: pageOf(request), signal: request.signal });
}

function Choice({ name, label, value, options, onChange }: {
  name: Key;
  label: string;
  value: string;
  options: [string, string][];
  onChange: (key: Key, value: string) => void;
}) {
  return (
    <label className="bar-field">
      {label}
      <select name={name} value={value} onChange={(event) => onChange(name, event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function named(blank: string, names: string[], chosen: string): [string, string][] {
  const listed = chosen && !names.includes(chosen) ? [...names, chosen] : names;
  return [["", blank], ...listed.map((name): [string, string] => [name, name])];
}

export function Usage() {
  const data = useLoaderData() as UsageData;
  const [, setSearchParams] = useSearchParams();
  useTitle("Usage");
  const { chosen, choices, report } = data;

  function choose(key: Key, value: string) {
    setSearchParams((current) => {
      const next = new URLSearchParams();
      for (const each of KEYS) {
        const kept = each === key ? value : current.get(each);
        if (kept) next.set(each, kept);
      }
      return next;
    });
  }

  return (
    <>
      <ContextBar>
        <h1 className="bar-title">Usage</h1>
        <Choice
          name="view"
          label="Show"
          value={chosen.view}
          onChange={choose}
          options={[
            ["", "Choose"],
            ["site", "Site group"],
            ["client", "Client group"],
            ["quota", "Quota"],
          ]}
        />
        <Choice name="client" label="Client group" value={chosen.client} onChange={choose} options={named("All client groups", choices.clients, chosen.client)} />
        <Choice name="site" label="Site group" value={chosen.site} onChange={choose} options={named("Choose", choices.sites, chosen.site)} />
        <Choice name="quota" label="Quota" value={chosen.quota} onChange={choose} options={named("Choose", choices.quotas, chosen.quota)} />
      </ContextBar>

      {data.message !== null && <p>{data.message}</p>}
      {report?.kind === "days" && (
        <>
          <h2>{report.heading}</h2>
          <p>{report.note}</p>
          {report.days.map((day) => (
            <section key={day.heading} className="day">
              <h3>{day.heading}</h3>
              {day.rows.length === 0 ? (
                <p>no usage</p>
              ) : (
                <>
                  <p>{day.summary}</p>
                  <table className="records">
                    <thead>
                      <tr>
                        <th scope="col">When</th>
                        {report.site_column && <th scope="col">Site group</th>}
                        <th scope="col">Time</th>
                        <th scope="col">Bytes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {day.rows.map((row, index) => (
                        <tr key={index}>
                          <td>{row.when}</td>
                          {report.site_column && <td>{row.site}</td>}
                          <td>{row.time}</td>
                          <td>{row.bytes}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </section>
          ))}
        </>
      )}
      {(report?.kind === "quota" || report?.kind === "balances") && (
        <>
          <h2>{report.heading}</h2>
          <p>{report.day}</p>
          {report.limits.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </>
      )}
      {report?.kind === "quota" && report.lines.map((line) => <p key={line}>{line}</p>)}
      {report?.kind === "balances" &&
        (report.rows.length === 0 ? (
          <p>{report.empty}</p>
        ) : (
          <table className="records">
            <thead>
              <tr>
                <th scope="col">Client group</th>
                <th scope="col">Ended time</th>
                <th scope="col">Stored bytes</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.client}>
                  <td>{row.client}</td>
                  <td>{row.time}</td>
                  <td>{row.bytes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}

      <StatusBar>
        <span>{data.times}</span>
      </StatusBar>
    </>
  );
}
