import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import type { CombineKind, CombineTask, Job } from "./types";
import { ChevronIcon, CombineIcon, DownloadIcon, SearchIcon, TrashIcon } from "./ui";

const PAGE = 10;

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** yyyy-mm-dd from a date input -> ISO instant at the start of that local day (+days). */
function dayStart(value: string, addDays = 0) {
  const d = new Date(`${value}T00:00:00`);
  d.setDate(d.getDate() + addDays);
  return d.toISOString();
}

/** page numbers with gaps, e.g. 1 … 4 5 6 … 12 */
export function pageList(page: number, pages: number): (number | "gap")[] {
  const want = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  const sorted = [...want].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

type Filters = { search: string; from: string; to: string };

/* ------------------------------------------------------------------ status + download */
function StatusBadge({ job }: { job: Job }) {
  if (job.status !== "SUCCESS") {
    return <span className="badge badge--err" title={job.error ?? ""}>Failed</span>;
  }
  const n = job.warnings?.length ?? 0;
  return n ? (
    <span className="badge badge--warn" title={(job.warnings ?? []).map((w) => w.message).join("\n")}>
      Completed · {n} warning{n > 1 ? "s" : ""}
    </span>
  ) : (
    <span className="badge badge--ok">Completed</span>
  );
}

export function DownloadMenu({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  // the table scrolls sideways on small screens, so the menu is placed with fixed coordinates
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const r = button.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, right: window.innerWidth - r.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e.type === "mousedown" && (menu.current?.contains(e.target as Node) || button.current?.contains(e.target as Node))) return;
      setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <>
      <button ref={button} type="button" className="dl" aria-haspopup="menu" aria-expanded={open}
              onClick={() => setOpen((o) => !o)}>
        Download <DownloadIcon />
      </button>
      {open && pos && (
        <div ref={menu} className="dl__menu" role="menu" style={{ top: pos.top, right: pos.right }}>
          {job.status === "SUCCESS" && (
            <a role="menuitem" href={api.outputUrl(job.id)} onClick={() => setOpen(false)}>
              <strong>Working template</strong>
              <span>{job.output_filename ?? "Output file"}</span>
            </a>
          )}
          {job.status === "SUCCESS" && job.submission_filename && (
            <a role="menuitem" href={api.submissionUrl(job.id)} onClick={() => setOpen(false)}>
              <strong>Submission template</strong>
              <span>{job.submission_filename}</span>
            </a>
          )}
          <a role="menuitem" href={api.inputUrl(job.id)} onClick={() => setOpen(false)}>
            <strong>Input file</strong>
            <span>{job.input_filename}</span>
          </a>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ combine */
const COMBINE_OPTIONS: { kind: CombineKind; label: string }[] = [
  { kind: "WORKING", label: "Working template" },
  { kind: "SUBMISSION", label: "Submission template" },
];

/** Why the selection cannot be combined into this template (null = it can). */
function combineBlocker(selected: Job[], kind: CombineKind): string | null {
  if (selected.length < 2) return "Select at least two completed conversions.";
  if (new Set(selected.map((j) => j.plant_type)).size > 1)
    return "Dukhan and Other-plant conversions use different templates – select one plant type.";
  if (kind === "SUBMISSION" && selected.some((j) => !j.submission_filename))
    return "Some selected conversions have no submission template.";
  return null;
}

function CombineMenu({ selected, busy, onPick }: {
  selected: Job[]; busy: boolean; onPick: (kind: CombineKind) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  // same fixed-position dropdown behaviour as the Download menu
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const r = button.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, right: window.innerWidth - r.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e.type === "mousedown" && (menu.current?.contains(e.target as Node) || button.current?.contains(e.target as Node))) return;
      setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const tooFew = selected.length < 2;
  return (
    <>
      <button ref={button} type="button" className="dl combine" aria-haspopup="menu" aria-expanded={open}
              disabled={busy || tooFew} onClick={() => setOpen((o) => !o)}
              title={tooFew ? "Select at least two conversions in the list to combine them" : undefined}>
        <CombineIcon /> Combine{selected.length ? ` (${selected.length})` : ""}
      </button>
      {open && pos && (
        <div ref={menu} className="dl__menu" role="menu" style={{ top: pos.top, right: pos.right }}>
          {COMBINE_OPTIONS.map(({ kind, label }) => {
            const blocker = combineBlocker(selected, kind);
            return (
              <button key={kind} type="button" role="menuitem" disabled={!!blocker}
                      onClick={() => { setOpen(false); onPick(kind); }}>
                <strong>{label}</strong>
                <span>{blocker ?? `Combine ${selected.length} files into one ${label.toLowerCase()}`}</span>
              </button>
            );
          })}
        </div>
      )}
    </>
  );
}

function CombineProgress({ task, onClose }: { task: CombineTask; onClose: () => void }) {
  const pct = task.total ? Math.round((task.done / task.total) * 100) : 0;
  const label = task.kind === "WORKING" ? "working template" : "submission template";
  return (
    <div className={`combine-card combine-card--${task.status.toLowerCase()}`} role="status" aria-live="polite">
      <div className="combine-card__head">
        <strong>
          {task.status === "RUNNING" && `Combining ${task.total} files into one ${label}…`}
          {task.status === "DONE" && `Combined ${task.total} files into one ${label}`}
          {task.status === "FAILED" && "Combining failed"}
        </strong>
        {task.status !== "RUNNING" && (
          <button type="button" className="h-clear" onClick={onClose}>Close</button>
        )}
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className="progress__bar" style={{ width: `${pct}%` }} />
      </div>
      <div className="combine-card__meta">
        <span>{task.done} of {task.total} files · {pct}%</span>
        {task.status === "DONE" && (
          <a href={api.combineFileUrl(task.id)}>Download again ({task.filename})</a>
        )}
      </div>
      {task.status === "FAILED" && <div className="alert alert--error">{task.error}</div>}
    </div>
  );
}

function download(url: string) {
  const a = document.createElement("a");
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ------------------------------------------------------------------ page */
export default function History({ refreshKey }: { refreshKey: number }) {
  const [search, setSearch] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [applied, setApplied] = useState<Filters>({ search: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [selected, setSelected] = useState<Map<number, Job>>(new Map());
  const [task, setTask] = useState<CombineTask | null>(null);
  const [starting, setStarting] = useState(false);
  const pageCheck = useRef<HTMLInputElement>(null);

  const badRange = !!from && !!to && from > to;

  const apply = (next: Filters) => {
    setApplied((prev) =>
      prev.search === next.search && prev.from === next.from && prev.to === next.to ? prev : next);
    setPage(1);
  };

  // typing searches by itself after a short pause; dates apply as soon as they change
  useEffect(() => {
    const t = setTimeout(() => apply({ search: search.trim(), from, to }), 300);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!badRange) apply({ search: search.trim(), from, to });
  }, [from, to]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let stale = false;
    setLoading(true);
    api.jobs({
      limit: PAGE, offset: (page - 1) * PAGE, search: applied.search || undefined,
      dateFrom: applied.from ? dayStart(applied.from) : undefined,
      dateTo: applied.to ? dayStart(applied.to, 1) : undefined, // "to" includes the whole day
    })
      .then((res) => { if (!stale) { setItems(res.items); setTotal(res.total); setError(null); } })
      .catch((e: Error) => { if (!stale) setError(e.message); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [applied, page, refreshKey, reload]);

  const remove = async (job: Job) => {
    const name = (job.spir_numbers ?? []).join(", ") || job.input_filename;
    if (!window.confirm(`Delete "${name}" from the history?

Its files are removed. The material temp numbers it issued stay in the material master.`)) return;
    setDeleting(job.id);
    try {
      await api.deleteJob(job.id);
      setSelected((prev) => { const next = new Map(prev); next.delete(job.id); return next; });
      if (items.length === 1 && page > 1) setPage(page - 1); // last row on this page
      else setReload((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeleting(null);
    }
  };

  // ---- selection (kept across pages and filters)
  const selectable = items.filter((j) => j.status === "SUCCESS");
  const pageAll = selectable.length > 0 && selectable.every((j) => selected.has(j.id));
  const pageSome = selectable.some((j) => selected.has(j.id));
  useEffect(() => {
    if (pageCheck.current) pageCheck.current.indeterminate = pageSome && !pageAll;
  }, [pageSome, pageAll]);

  const toggle = (job: Job) => setSelected((prev) => {
    const next = new Map(prev);
    if (next.has(job.id)) next.delete(job.id); else next.set(job.id, job);
    return next;
  });
  const togglePage = () => setSelected((prev) => {
    const next = new Map(prev);
    selectable.forEach((j) => (pageAll ? next.delete(j.id) : next.set(j.id, j)));
    return next;
  });

  // ---- combine: start, then poll the progress until it is done
  const combining = starting || task?.status === "RUNNING";
  const startCombine = async (kind: CombineKind) => {
    setStarting(true);
    setError(null);
    try {
      setTask(await api.combine([...selected.keys()], kind));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    if (task?.status !== "RUNNING") return;
    const t = setTimeout(() => {
      api.combineStatus(task.id)
        .then((next) => {
          setTask(next);
          if (next.status === "DONE") {
            download(api.combineFileUrl(next.id));
            setSelected(new Map());
          }
        })
        .catch((e: Error) => setTask({ ...task, status: "FAILED", error: e.message }));
    }, 500);
    return () => clearTimeout(t);
  }, [task]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!badRange) apply({ search: search.trim(), from, to });
  };

  const filtered = !!(applied.search || applied.from || applied.to);
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const first = total ? (page - 1) * PAGE + 1 : 0;
  const last = Math.min(page * PAGE, total);

  return (
    <section className="history">
      <div className="h-top">
        <h1 className="page-title">History</h1>
        <div className="h-top__actions">
          {selected.size > 0 && (
            <span className="h-selected">
              {selected.size} selected
              <button type="button" className="h-clear" disabled={combining}
                      onClick={() => setSelected(new Map())}>Clear selection</button>
            </span>
          )}
          <CombineMenu selected={[...selected.values()]} busy={combining} onPick={startCombine} />
        </div>
      </div>
      <p className="page-sub">View and manage your past extractions and batch processing history.</p>

      <div className="h-card">
        <form className="h-filters" onSubmit={submit} role="search">
          <label className="h-field h-field--search">
            <span>Search</span>
            <div className="h-search">
              <SearchIcon />
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                     placeholder="Search by SPIR number, file name, user or plant…" />
            </div>
          </label>
          <label className="h-field">
            <span>From date</span>
            <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="h-field">
            <span>To date</span>
            <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
          </label>
          <button type="submit" className="primary h-go" disabled={badRange}>Search</button>
          {(search || from || to) && (
            <button type="button" className="h-clear"
                    onClick={() => { setSearch(""); setFrom(""); setTo(""); apply({ search: "", from: "", to: "" }); }}>
              Clear
            </button>
          )}
        </form>
        {badRange && <div className="alert alert--error">“From date” must be on or before “To date”.</div>}
        {error && <div className="alert alert--error">{error}</div>}
        {task && <CombineProgress task={task} onClose={() => setTask(null)} />}

        <div className="table-wrap h-table" aria-busy={loading}>
          <table>
            <thead>
              <tr>
                <th className="h-check">
                  <input ref={pageCheck} type="checkbox" aria-label="Select all completed conversions on this page"
                         checked={pageAll} disabled={!selectable.length || combining} onChange={togglePage} />
                </th>
                <th>SPIR name</th><th className="num">Total tags</th><th>Plant</th><th>User</th>
                <th>Date &amp; time</th><th>Status</th><th className="act">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id} className={selected.has(j.id) ? "h-row--selected" : undefined}>
                  <td className="h-check">
                    <input type="checkbox" checked={selected.has(j.id)}
                           disabled={j.status !== "SUCCESS" || combining}
                           aria-label={`Select conversion ${j.id}`}
                           title={j.status !== "SUCCESS" ? "Failed conversions cannot be combined" : undefined}
                           onChange={() => toggle(j)} />
                  </td>
                  <td className="h-spir">
                    <strong>{(j.spir_numbers ?? []).join(", ") || "—"}</strong>
                    <span title={j.input_filename}>{j.input_filename}</span>
                  </td>
                  <td className="num">
                    {j.status === "SUCCESS" ? (
                      <>
                        <strong>{j.equipment_count}</strong>
                        <span className="sub">{j.line_count} BOM lines</span>
                      </>
                    ) : "—"}
                  </td>
                  <td>
                    <strong>{j.plant_code ?? "—"}</strong>
                    <span className="sub">{j.plant_type === "DUKHAN" ? "Dukhan" : "Other plant"}</span>
                  </td>
                  <td>{j.user_name ?? "—"}</td>
                  <td className="nowrap">{formatDate(j.created_at)}</td>
                  <td><StatusBadge job={j} /></td>
                  <td className="act">
                    <div className="h-actions">
                      <DownloadMenu job={j} />
                      <button type="button" className="del" title="Delete" aria-label={`Delete conversion ${j.id}`}
                              disabled={deleting === j.id} onClick={() => remove(j)}>
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr><td colSpan={8} className="empty">
                  {filtered ? "No conversions match these filters." : "No conversions yet."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="h-foot">
          <span>{total ? `Showing ${first}–${last} of ${total}` : loading ? "Loading…" : "Showing 0 of 0"}</span>
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">
                <ChevronIcon dir="left" />
              </button>
              {pageList(page, pages).map((p, i) => p === "gap"
                ? <span key={`gap${i}`} className="pager__gap">…</span>
                : (
                  <button key={p} type="button" className={p === page ? "pager--on" : ""}
                          aria-current={p === page ? "page" : undefined} onClick={() => setPage(p)}>
                    {p}
                  </button>
                ))}
              <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">
                <ChevronIcon dir="right" />
              </button>
            </nav>
          )}
        </div>
      </div>
    </section>
  );
}
