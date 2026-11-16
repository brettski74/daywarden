import { SquarePlus } from "lucide-react";
import { useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, type LoaderFunctionArgs } from "react-router";
import { ApiError, api, pageOf } from "../api";
import { NameDialog } from "../components/NameDialog";
import { DEFAULT_LEVEL } from "../sentences";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { POOLS, POOLS_DATA, poolPath, type PoolEntry, type PoolReport } from "../pools";
import { Outcome } from "./Task";

type Listing = { pools: PoolEntry[] };
type Made = { message: string; warnings: string[]; pool: { id: string; name: string } };

export const TITLE = "Parts of Speech Pools";
export const NEW_POOL = "New pool";

export async function poolsLoader({ request }: LoaderFunctionArgs): Promise<Listing> {
  return api<Listing>(POOLS_DATA, { page: pageOf(request), signal: request.signal });
}

/** Every parts of speech pool, with a way to make a new one. */
export function Pools() {
  const { pools } = useLoaderData() as Listing;
  const reported = useLocation().state as PoolReport | null;
  const navigate = useNavigate();
  const [naming, setNaming] = useState(false);
  useTitle(TITLE);

  async function make(name: string): Promise<string | null> {
    try {
      const made = await api<Made>(POOLS_DATA, { page: `/parent${POOLS}`, method: "POST", body: { name }, signedOut: "refuse" });
      setNaming(false);
      navigate(poolPath(made.pool.id), { state: { message: made.message, warnings: made.warnings } satisfies PoolReport });
      return null;
    } catch (error) {
      if (error instanceof ApiError) return error.message;
      throw error;
    }
  }

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Asset Administration</li>
            <li>
              <h1 className="bar-title">{TITLE}</h1>
            </li>
          </ol>
        </nav>
        <div className="bar-end bar-actions">
          <button type="button" className="button" onClick={() => setNaming(true)}>
            <SquarePlus aria-hidden="true" />
            {NEW_POOL}
          </button>
        </div>
      </ContextBar>

      {pools.length === 0 ? (
        <p>There are no parts of speech pools yet. Make one with {NEW_POOL}.</p>
      ) : (
        <table className="records pools-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col" title="level_of_difficulty">
                Level of Difficulty
              </th>
              <th scope="col">Sentences</th>
            </tr>
          </thead>
          <tbody>
            {pools.map((pool) => (
              <tr key={pool.id}>
                <td>
                  <Link to={poolPath(pool.id)}>{pool.name}</Link>
                  {pool.problem && <span className="note note-problem"> {pool.problem}</span>}
                </td>
                <td className="pools-number">{pool.level_of_difficulty || DEFAULT_LEVEL}</td>
                <td className="pools-number">{pool.sentences}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <StatusBar>
        {reported?.message && <Outcome result={{ ok: true, ...reported }} />}
        <span>
          {pools.length} pool{pools.length === 1 ? "" : "s"}.
        </span>
      </StatusBar>

      {naming && <NameDialog title="New parts of speech pool" label="Name" onSubmit={make} onCancel={() => setNaming(false)} />}
    </>
  );
}
