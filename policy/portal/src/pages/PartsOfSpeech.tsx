import { ArrowDown, ArrowUp, Plus, SquarePen, X } from "lucide-react";
import { Link } from "react-router";
import { MultiSelect } from "../components/MultiSelect";
import { label } from "../labels";
import {
  CAPITALISATION_TIMEOUT,
  DEFAULT_TIMEOUT,
  FILTER_LABEL,
  NO_POOLS,
  SETTINGS,
  filterProblem,
  filterWarning,
  poolOptions,
  questionPlaceholders,
  runnableSize,
  sameList,
  type PosData,
} from "../partsOfSpeech";
import { CAPITALISATION_POOLS, PARTS_POOLS, poolPath } from "../pools";

export type { PosData };

type Props = {
  /** A capitalisation task has no filter of parts, and its page names its own pools and defaults. */
  data: Omit<PosData, "filter"> & { filter?: string[] };
  settings: Record<string, string>;
  /** The pools and the filter on show, which are the file's until the parent changes them. */
  pools: string[];
  /** The parts of speech filter on show, or null for a capitalisation task, which has none. */
  filter: string[] | null;
  onSetting: (key: string, text: string) => void;
  onPools: (pools: string[]) => void;
  onFilter: (filter: string[]) => void;
};

/**
 * A parts of speech or capitalisation task's own settings, the pools it draws on, and a parts of speech task's filter.
 * Its sentences are edited in their pools under Asset Administration.
 */
export function PartsOfSpeechAdmin({ data, settings, pools, filter, onSetting, onPools, onFilter }: Props) {
  const capital = filter === null;
  const kind = capital ? CAPITALISATION_POOLS : PARTS_POOLS;
  const options = poolOptions(data, pools);
  const placeholders = { timeout: capital ? CAPITALISATION_TIMEOUT : DEFAULT_TIMEOUT, ...questionPlaceholders(runnableSize(data, pools), settings) } as Record<string, string>;
  const toggle = (name: string) => onPools(options.filter((option) => (option === name ? !pools.includes(name) : pools.includes(option))));
  const move = (index: number, by: number) => {
    if (filter === null) return;
    const next = [...filter];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    onFilter(next);
  };
  return (
    <section className="parts-of-speech" aria-label={capital ? "Capitalisation" : "Parts of speech"}>
      <div className="task-common">
        <fieldset>
          <legend>{capital ? "Capitalisation settings" : "Parts of speech settings"}</legend>
          <div className="settings">
            {SETTINGS.map((key) => {
              const written = data.settings[key] ?? "";
              const shown = settings[key] ?? written;
              return (
                <label key={key} className="setting">
                  <span title={key}>{label(key)}</span>
                  <input
                    type="text"
                    inputMode={key === "timeout" ? undefined : "numeric"}
                    value={shown}
                    placeholder={placeholders[key]}
                    data-changed={shown.trim() !== written.trim() || undefined}
                    onChange={(event) => onSetting(key, event.target.value)}
                  />
                </label>
              );
            })}
          </div>
        </fieldset>
        <fieldset>
          <legend>Sentences</legend>
          <MultiSelect
            label="Pools"
            options={options}
            selected={pools}
            onToggle={toggle}
            changed={!sameList([...pools].sort(), [...data.pools].sort())}
            empty="None chosen"
          />
          {pools.length === 0 && <p className="note note-problem">{NO_POOLS}</p>}
          <ul className="pool-links">
            {pools.map((name) => {
              const found = data.available.find((pool) => pool.name === name);
              return (
                <li key={name}>
                  {found ? (
                    <Link to={poolPath(found.id, kind)}>
                      <SquarePen aria-hidden="true" />
                      Edit {name}
                    </Link>
                  ) : (
                    <span className="note note-problem">There is no pool named {name}.</span>
                  )}
                </li>
              );
            })}
          </ul>
        </fieldset>
      </div>
      {filter !== null && (
      <fieldset className="parts-filter">
        <legend title="parts_of_speech">{FILTER_LABEL}</legend>
        <p className="note">
          With no names, each sentence uses its own parts. With names, every question shows exactly these rows, in this order.
        </p>
        <ol>
          {filter.map((name, index) => {
            const problem = filterProblem(filter, index);
            const warning = problem === null ? filterWarning(name) : null;
            return (
              <li key={index}>
                <input
                  type="text"
                  aria-label={`Part ${index + 1}`}
                  value={name}
                  aria-invalid={problem !== null || undefined}
                  data-changed={name.trim() !== (data.filter?.[index] ?? "") || undefined}
                  onChange={(event) => onFilter(filter.map((each, at) => (at === index ? event.target.value : each)))}
                />
                <button type="button" className="button button-quiet" aria-label={`Move part ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}>
                  <ArrowUp aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="button button-quiet"
                  aria-label={`Move part ${index + 1} down`}
                  disabled={index === filter.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown aria-hidden="true" />
                </button>
                <button type="button" className="button button-quiet" aria-label={`Remove part ${index + 1}`} onClick={() => onFilter(filter.filter((_each, at) => at !== index))}>
                  <X aria-hidden="true" />
                </button>
                {problem && <span className="note note-problem">{problem}</span>}
                {warning && <span className="note">{warning}</span>}
              </li>
            );
          })}
        </ol>
        <button type="button" className="button button-quiet" onClick={() => onFilter([...filter, ""])}>
          <Plus aria-hidden="true" />
          Add part
        </button>
      </fieldset>
      )}
      <p>
        The sentences are in the pools this task names. Edit them under Asset Administration ›{" "}
        <Link to={kind.list}>{kind.title}</Link>.
      </p>
    </section>
  );
}
