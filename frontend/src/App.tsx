import { useEffect, useRef, useState } from "react";
import { api, SIGNED_OUT_EVENT } from "./api";
import LoginPage from "./LoginPage";
import logo from "./assets/cdc-logo.jpg";
import type { Job, Plant, User } from "./types";
import History, { DownloadMenu } from "./History";
import PartsMaster from "./PartsMaster";
import Settings from "./Settings";
import { BoxIcon, ClockIcon, DownloadIcon, GearIcon, initials, LayersIcon, UploadIcon } from "./ui";

const isExcel = (f: File) => /\.xls[xm]$/i.test(f.name);

/* ------------------------------------------------------------------ plant picker (shared) */
function PlantFields({ plants, plantId, onChange, disabled }: {
  plants: Plant[]; plantId: number | ""; onChange: (id: number | "") => void; disabled?: boolean;
}) {
  const plant = plants.find((p) => p.id === plantId);
  return (
    <div className="grid plant-box">
  <label className="field">
    <span className="label">
      MAINTENANCE PLAINNING PLANT
      <em
        style={{
          color: "#ff0000",
          fontSize: "14px",
          fontWeight: "bold",
          fontStyle: "normal",
          marginLeft: "4px",
          lineHeight: 1
        }}
      >
        *
      </em>
    </span>

    <select
      value={plantId}
      disabled={disabled}
      onChange={(e) =>
        onChange(e.target.value ? Number(e.target.value) : "")
      }
    >
      <option value="">Select plant…</option>
      {plants.map((p) => (
        <option key={p.id} value={p.id}>
          {p.code}
        </option>
      ))}
    </select>
  </label>

  <label className="field">
    <span className="label">MPP DESCRIPTION</span>

    <input
      value={plant?.name ?? ""}
      readOnly
      placeholder="Shown when a plant is selected"
    />
  </label>
</div>

  );
}

/* ------------------------------------------------------------------ batch converter */
type BatchItem = {
  id: number;
  file: File;
  status: "waiting" | "running" | "done" | "failed";
  job?: Job;
  error?: string;
};

let batchSeq = 0;

function BatchPanel({ onConverted, onBusyChange }: { onConverted: () => void; onBusyChange?: (busy: boolean) => void }) {
  const [plants, setPlants] = useState<Plant[]>([]);
  const [plantId, setPlantId] = useState<number | "">("");
  const [items, setItems] = useState<BatchItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { onBusyChange?.(busy); }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.plants().then(setPlants).catch((e: Error) => setError(e.message));
  }, []);

  const plant = plants.find((p) => p.id === plantId);

  const addFiles = (list: FileList | null | undefined) => {
    if (busy || !list) return;
    const files = Array.from(list);
    const rejected = files.filter((f) => !isExcel(f)).map((f) => f.name);
    setError(rejected.length ? `Skipped (not .xlsx / .xlsm): ${rejected.join(", ")}` : null);
    setItems((prev) => {
      // a finished batch is replaced by the next one
      const keep = prev.every((i) => i.status === "waiting") ? prev : [];
      const seen = new Set(keep.map((i) => `${i.file.name}|${i.file.size}`));
      const added = files
        .filter((f) => isExcel(f) && !seen.has(`${f.name}|${f.size}`))
        .map((f): BatchItem => ({ id: ++batchSeq, file: f, status: "waiting" }));
      return [...keep, ...added];
    });
  };

  const update = (id: number, patch: Partial<BatchItem>) =>
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));

  // one file at a time, in list order, so temp numbers continue in sequence for the plant
  const submit = async () => {
    if (!plant) return;
    const queue = items.filter((i) => i.status !== "done");
    if (!queue.length) return;
    setBusy(true);
    setError(null);
    for (const item of queue) {
      update(item.id, { status: "running", error: undefined });
      try {
        const job = await api.convert({ plantType: plant.plant_type, plantId: plant.id, file: item.file });
        update(item.id, { status: "done", job });
      } catch (e) {
        update(item.id, { status: "failed", error: (e as Error).message });
      }
    }
    setBusy(false);
    onConverted();
  };

  const done = items.filter((i) => i.status === "done").length;
  const failed = items.filter((i) => i.status === "failed").length;
  const pending = items.length - done;
  const running = items.findIndex((i) => i.status === "running");
  const canSubmit = !!plant && pending > 0 && !busy;

  return (
    <section className="extract">
      <h1 className="page-title">Batch Extraction</h1>
      <p className="page-sub">Upload a set of SPIR files (.xlsx / .xlsm). Each file gets its own filled BOM working template.</p>

      <div className="extract__body">
      <PlantFields plants={plants} plantId={plantId} onChange={setPlantId} disabled={busy} />

      <div
        className={`drop ${dragging ? "drop--over" : ""} ${busy ? "drop--busy" : ""}`}
        onClick={() => !busy && fileInput.current?.click()}
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        role="button" tabIndex={0} aria-disabled={busy}
        onKeyDown={(e) => { if (!busy && (e.key === "Enter" || e.key === " ")) fileInput.current?.click(); }}
      >
        <input ref={fileInput} type="file" accept=".xlsx,.xlsm" multiple hidden
               onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
        <span className="drop__icon"><LayersIcon /></span>
        <strong>SPIR Excel Batch Upload</strong>
        <span>Drag and drop your SPIR Excel files here, or click to browse</span>
        <small>Supports .xlsx, .xlsm · select several files at once</small>
      </div>

      {items.length > 0 && (
        <div className="batch">
          <div className="batch__head">
            <strong>{items.length} file{items.length > 1 ? "s" : ""}</strong>
            <span>
              {busy ? `Converting ${running + 1} of ${items.length}…`
                : done || failed ? `${done} converted${failed ? `, ${failed} failed` : ""}` : "Ready to convert"}
            </span>
          </div>
          <ul className="batch__list">
            {items.map((i) => (
              <li key={i.id} className={`batch__row batch__row--${i.status}`}>
                <div className="batch__file">
                  <span className="batch__name" title={i.file.name}>{i.file.name}</span>
                  <span className="batch__meta">
                    {i.status === "done" && i.job
                      ? `${i.job.line_count} BOM lines${i.job.warnings?.length ? ` · ${i.job.warnings.length} warning${i.job.warnings.length > 1 ? "s" : ""}` : ""}`
                      : i.status === "failed" ? i.error
                      : `${(i.file.size / 1024).toFixed(0)} KB`}
                  </span>
                </div>
                <div className="batch__actions">
                  {i.status === "waiting" && <span className="badge">Waiting</span>}
                  {i.status === "running" && <span className="badge badge--run">Converting…</span>}
                  {i.status === "failed" && <span className="badge badge--err">Failed</span>}
                  {i.status === "done" && i.job && <DownloadMenu job={i.job} />}
                  {!busy && i.status !== "done" && (
                    <button type="button" className="remove" aria-label={`Remove ${i.file.name}`}
                            onClick={() => setItems((prev) => prev.filter((x) => x.id !== i.id))}>×</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="actions">
        <button className="primary" disabled={!canSubmit} onClick={submit}>
          {busy ? "Converting…"
            : done > 0 && pending === failed ? `Retry ${failed} failed file${failed > 1 ? "s" : ""}`
            : `Generate ${pending > 1 ? `${pending} BOM templates` : "BOM template"}`}
        </button>
        {items.length > 0 && !busy && (
          <button className="secondary" onClick={() => { setItems([]); setError(null); }}>Clear list</button>
        )}
        {!plant && <span className="hint">Select the maintenance planning plant first.</span>}
      </div>

      {error && <div className="alert alert--error">{error}</div>}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ converter form */
function ConvertPanel({ onConverted, onBusyChange }: { onConverted: () => void; onBusyChange?: (busy: boolean) => void }) {
  const [plants, setPlants] = useState<Plant[]>([]);
  const [plantId, setPlantId] = useState<number | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Job | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { onBusyChange?.(busy); }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.plants().then(setPlants).catch((e: Error) => setError(e.message));
  }, []);

  // the selected plant decides the template (Dukhan / Other)
  const plant = plants.find((p) => p.id === plantId);

  const pickFile = (f: File | undefined | null) => {
    setResult(null);
    setError(null);
    if (!f) return;
    if (!/\.xls[xm]$/i.test(f.name)) {
      setError("Please choose an Excel .xlsx file.");
      return;
    }
    setFile(f);
  };

  const submit = async () => {
    if (!plant || !file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const job = await api.convert({ plantType: plant.plant_type, plantId: plant.id, file });
      setResult(job);
      onConverted();
    } catch (e) {
      setError((e as Error).message);
      onConverted(); // refresh history (failed attempts are logged too)
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = !!plant && !!file && !busy;

  return (
    <section className="extract">
      <h1 className="page-title">Extraction</h1>
      <p className="page-sub">Upload a SPIR (.xlsx / .xlsm). You'll get the filled BOM working template.</p>

      <div className="extract__body">
      <PlantFields plants={plants} plantId={plantId} onChange={setPlantId} />

      <div
        className={`drop ${dragging ? "drop--over" : ""} ${file ? "drop--has" : ""}`}
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files[0]); }}
        role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") fileInput.current?.click(); }}
      >
        <input ref={fileInput} type="file" accept=".xlsx,.xlsm" hidden
               onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
        <span className="drop__icon"><UploadIcon /></span>
        {file ? (
          <>
            <strong>{file.name}</strong>
            <span>{(file.size / 1024).toFixed(0)} KB · click to choose another file</span>
          </>
        ) : (
          <>
            <strong>SPIR Excel File Upload</strong>
            <span>Drag and drop your SPIR Excel file here, or click to browse</span>
            <small>Supports .xlsx, .xlsm</small>
          </>
        )}
      </div>

      <div className="actions">
        <button className="primary" disabled={!canSubmit} onClick={submit}>
          {busy ? "Converting…" : "Generate BOM template"}
        </button>
        {!plant && <span className="hint">Select the maintenance planning plant first.</span>}
      </div>

      {error && <div className="alert alert--error">{error}</div>}
      {result && <ResultView job={result} />}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ result */
function ResultView({ job }: { job: Job }) {
  return (
    <div className="result">
      <div className="result__head">
        <div className="result__title">BOM templates ready</div>
      </div>
      <div className="files">
        <a className="file-dl" href={api.outputUrl(job.id)}>
          <DownloadIcon />
          <span><strong>Working template</strong><small>{job.output_filename}</small></span>
        </a>
        {job.submission_filename && (
          <a className="file-dl" href={api.submissionUrl(job.id)}>
            <DownloadIcon />
            <span><strong>Submission template</strong><small>{job.submission_filename}</small></span>
          </a>
        )}
      </div>
      <div className="stats">
        <Stat label="SPIR number" value={(job.spir_numbers ?? []).join(", ") || "—"} />
        <Stat label="Template" value={job.plant_type === "DUKHAN" ? "Dukhan" : "Other plant"} />
        <Stat label="Planning plant" value={job.plant_code ?? "—"} />
      </div>
      
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ page */
export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = still checking

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
    const signedOut = () => setUser(null);
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, []);

  if (user === undefined) return null;
  if (user === null) return <LoginPage onSignedIn={setUser} />;
  return <Workspace user={user} onSignOut={() => { api.logout().finally(() => setUser(null)); }} />;
}

/* ------------------------------------------------------------------ shell */
type View = "extraction" | "batch" | "history" | "parts" | "settings";

const NAV: { key: string; label: string; icon: () => JSX.Element; view?: View }[] = [
  { key: "extraction", label: "Extraction", icon: UploadIcon, view: "extraction" },
  { key: "batch", label: "Batch Extraction", icon: LayersIcon, view: "batch" },
  { key: "history", label: "History", icon: ClockIcon, view: "history" },
  { key: "parts", label: "Parts Master", icon: BoxIcon, view: "parts" },
  { key: "settings", label: "Settings", icon: GearIcon, view: "settings" },
];

function AccountMenu({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  return (
    <div className="account" ref={box}>
      <button type="button" className="avatar" aria-haspopup="menu" aria-expanded={open}
              title={user.full_name || user.username} onClick={() => setOpen((o) => !o)}>
        {initials(user)}
      </button>
      {open && (
        <div className="account__menu" role="menu">
          <div className="account__name">{user.full_name || user.username}</div>
          {user.email && <div className="account__email">{user.email}</div>}
          <button type="button" role="menuitem" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function Workspace({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [view, setView] = useState<View>("extraction");
  // Extraction and Batch Extraction stay mounted while you visit other pages, so a running upload /
  // batch keeps going and its progress and result are still there when you come back.
  const [running, setRunning] = useState<Record<"extraction" | "batch", boolean>>({ extraction: false, batch: false });
  const anyRunning = running.extraction || running.batch;

  // reloading or closing the tab WOULD stop a running extraction - let the browser ask first
  useEffect(() => {
    if (!anyRunning) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [anyRunning]);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <img src={logo} alt="CDC" />
          <span>SPIR BOM TOOL</span>
        </div>
        <AccountMenu user={user} onSignOut={onSignOut} />
      </header>
      <nav className="sidebar">
        {NAV.map(({ key, label, icon: Icon, view: target }) => (
          <button key={key} type="button"
                  className={`nav ${target === view ? "nav--active" : ""}`}
                  disabled={!target} title={target ? undefined : "Coming soon"}
                  aria-current={target === view ? "page" : undefined}
                  onClick={() => target && setView(target)}>
            <Icon />
            <span>{label}</span>
            {(key === "extraction" || key === "batch") && running[key] && (
              <span className="nav__running" title="Extraction in progress" aria-label="in progress" />
            )}
          </button>
        ))}
      </nav>
      <main className="content">
        <div hidden={view !== "extraction"}>
          <ConvertPanel onConverted={() => setRefreshKey((k) => k + 1)}
                        onBusyChange={(busy) => setRunning((r) => ({ ...r, extraction: busy }))} />
        </div>
        <div hidden={view !== "batch"}>
          <BatchPanel onConverted={() => setRefreshKey((k) => k + 1)}
                      onBusyChange={(busy) => setRunning((r) => ({ ...r, batch: busy }))} />
        </div>
        {view === "history" && <History refreshKey={refreshKey} />}
        {view === "parts" && <PartsMaster />}
        {view === "settings" && <Settings user={user} />}
      </main>
    </div>
  );
}
