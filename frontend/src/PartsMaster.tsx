import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { pageList } from "./History";
import type { Part, PartField, PartPage } from "./types";
import { ChevronIcon, DownloadIcon, SearchIcon } from "./ui";

const PAGE = 25;

const FIELDS: { value: PartField; label: string }[] = [
  { value: "part_number", label: "Part Number" },
  { value: "tag_number", label: "Tag Number" },
  { value: "sap_material_number", label: "SAP Material Number" },
  { value: "material_temp_number", label: "Material Temp Number" },
  { value: "material_category", label: "Material Type / Category" },
  { value: "description", label: "New Description of Parts" },
  { value: "planning_plant", label: "Maintenance Planning Plant" },
  { value: "manufacturer_name", label: "Manufacturer Name" },
  { value: "country_name", label: "Manufacturer Country Name" },
  { value: "spir", label: "SPIR" },
];

const CATEGORY: Record<string, string> = { B: "Equipment", L: "Spare" };

/* Result columns: width = share of the table width (%). The table always fits the results card (no
   sideways scrolling); long values wrap inside their column. */
const COLUMNS: { label: string; width: number; className?: string }[] = [
  { label: "Temp number", width: 8, className: "pm-nowrap" },
  { label: "Type", width: 7 },
  { label: "Part number", width: 11 },
  { label: "Description", width: 20 },
  { label: "Tag", width: 10 },
  { label: "SAP number", width: 8 },
  { label: "Plant", width: 6, className: "pm-nowrap" },
  { label: "Manufacturer", width: 11 },
  { label: "Country", width: 8 },
  { label: "SPIR", width: 11 },
];

type Query = { field: PartField; q: string };

function Cell({ value }: { value: string | null }) {
  return value ? <>{value}</> : <span className="pm-empty">—</span>;
}

export default function PartsMaster() {
  const [field, setField] = useState<PartField>("part_number");
  const [value, setValue] = useState("");
  const [query, setQuery] = useState<Query | null>(null); // the search that is shown
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<PartPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query) return;
    let stale = false;
    setLoading(true);
    setError(null);
    api.parts({ ...query, limit: PAGE, offset: (page - 1) * PAGE })
      .then((res) => { if (!stale) setResult(res); })
      .catch((e: Error) => { if (!stale) { setError(e.message); setResult(null); } })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [query, page]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    setPage(1);
    setQuery({ field, q }); // a new object, so pressing Search again re-runs the same search
  };

  const total = result?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const first = total ? (page - 1) * PAGE + 1 : 0;
  const last = Math.min(page * PAGE, total);
  const fieldLabel = FIELDS.find((f) => f.value === query?.field)?.label;

  return (
    <section className="pm">
      <div className="card pm-card">
        <h1 className="page-title">Parts Master</h1>
        <p className="page-sub">Search every extracted record by the field you choose.</p>

        <form className="pm-form" onSubmit={submit} role="search">
          <label className="h-field pm-field">
            <span>Search by</span>
            <select value={field} onChange={(e) => setField(e.target.value as PartField)}>
              {FIELDS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
          <label className="h-field pm-value">
            <span>Value</span>
            <div className="h-search">
              <SearchIcon />
              <input type="search" value={value} maxLength={200} onChange={(e) => setValue(e.target.value)}
                     placeholder="Enter a value — use * as a wildcard, e.g. 12* or *12*" />
            </div>
          </label>
          <button type="submit" className="primary pm-go" disabled={!value.trim() || loading}>
            <SearchIcon /> Search
          </button>
          {/* downloads the search shown below (every page of it), or every record before any search */}
          <a className={`button dl pm-dl${loading ? " pm-dl--busy" : ""}`} href={api.partsExportUrl(query)}
             aria-disabled={loading}
             title={query ? "Download all results of this search as Excel (Material Master layout)"
                          : "Download all Parts Master records as Excel (Material Master layout)"}>
            <DownloadIcon /> {query ? "Download" : "Download all"}
          </a>
        </form>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {query && !error && (
        <div className="h-card pm-results">
          <div className="pm-results__head">
            <strong>
              {loading && !result ? "Searching…" : `${total.toLocaleString()} result${total === 1 ? "" : "s"}`}
            </strong>
            <span>{fieldLabel}: “{query.q}”</span>
          </div>

          {result && total === 0 && !loading ? (
            <div className="empty pm-none">
              No records match this value. Check the spelling, or use * as a wildcard (e.g. {query.q.replace(/\*/g, "")}* ).
            </div>
          ) : (
            <div className="table-wrap pm-table" aria-busy={loading}>
              <table>
                <colgroup>
                  {COLUMNS.map((c) => <col key={c.label} style={{ width: `${c.width}%` }} />)}
                </colgroup>
                <thead>
                  <tr>{COLUMNS.map((c) => <th key={c.label} scope="col">{c.label}</th>)}</tr>
                </thead>
                <tbody>
                  {(result?.items ?? []).map((p: Part, i) => (
                    <tr key={`${p.source}-${p.job_id ?? "m"}-${first + i}`}>
                      <td className="pm-nowrap pm-strong"><Cell value={p.material_temp_number} /></td>
                      <td className="pm-nowrap">{p.material_category ? (CATEGORY[p.material_category] ?? p.material_category) : <Cell value={null} />}</td>
                      <td className="pm-code"><Cell value={p.part_number} /></td>
                      <td><Cell value={p.description} /></td>
                      <td><Cell value={p.tag_number} /></td>
                      <td><Cell value={p.sap_material_number} /></td>
                      <td className="pm-nowrap"><Cell value={p.planning_plant} /></td>
                      <td><Cell value={p.manufacturer_name} /></td>
                      <td><Cell value={p.country_name} /></td>
                      <td className="pm-code"><Cell value={p.spir} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {total > 0 && (
            <div className="h-foot">
              <span>Showing {first}–{last} of {total.toLocaleString()}</span>
              {pages > 1 && (
                <nav className="pager" aria-label="Pages">
                  <button type="button" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)} aria-label="Previous page">
                    <ChevronIcon dir="left" />
                  </button>
                  {pageList(page, pages).map((p, i) => p === "gap"
                    ? <span key={`gap${i}`} className="pager__gap">…</span>
                    : (
                      <button key={p} type="button" className={p === page ? "pager--on" : ""} disabled={loading}
                              aria-current={p === page ? "page" : undefined} onClick={() => setPage(p)}>
                        {p}
                      </button>
                    ))}
                  <button type="button" disabled={page >= pages || loading} onClick={() => setPage(page + 1)} aria-label="Next page">
                    <ChevronIcon dir="right" />
                  </button>
                </nav>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
