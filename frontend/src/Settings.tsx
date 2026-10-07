import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api } from "./api";
import { applyTheme, storedTheme, type Theme } from "./theme";
import type { Profile, User } from "./types";
import { EyeIcon, initials, LockIcon, SlidersIcon, UserIcon } from "./ui";

const MIN_PASSWORD = 8; // same rule as the server

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function Card({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="s-card">
      <h2 className="s-card__head"><span className="s-card__icon">{icon}</span>{title}</h2>
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ profile */
function ProfileCard({ user }: { user: User }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.profile().then(setProfile).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <Card icon={<UserIcon />} title="Profile">
      <div className="profile">
        <span className="profile__avatar">{initials(user)}</span>
        <div className="profile__who">
          <div className="profile__name">{user.full_name || user.username}</div>
          {user.email && <div className="profile__email">{user.email}</div>}
        </div>
      </div>

      <dl className="profile__info">
        <div><dt>Username</dt><dd>{user.username}</dd></div>
        <div><dt>Full name</dt><dd>{user.full_name || "—"}</dd></div>
      </dl>

      {error && <div className="alert alert--error">{error}</div>}
      <div className="profile__stats">
        <div className="pstat">
          <div className="pstat__value">{profile ? profile.extraction_count : "…"}</div>
          <div className="pstat__label">Extractions</div>
        </div>
        <div className="pstat">
          <div className="pstat__value pstat__value--date">{profile ? formatDate(profile.last_login) : "…"}</div>
          <div className="pstat__label">Last login</div>
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ password */
function PasswordField({ label, value, onChange, autoComplete }: {
  label: string; value: string; onChange: (v: string) => void; autoComplete: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <label className="s-field">
      <span>{label}</span>
      <div className="s-password">
        <input type={show ? "text" : "password"} value={value} autoComplete={autoComplete}
               onChange={(e) => onChange(e.target.value)} required />
        <button type="button" className="s-eye" onClick={() => setShow((v) => !v)}
                aria-label={show ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`} aria-pressed={show}>
          <EyeIcon open={show} />
        </button>
      </div>
    </label>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setDone(false);
    if (!current || !next || !confirm) return setError("Fill in all three password fields.");
    if (next.length < MIN_PASSWORD) return setError(`New password must be at least ${MIN_PASSWORD} characters.`);
    if (next !== confirm) return setError("New password and confirmation do not match.");
    if (next === current) return setError("New password must be different from the current password.");
    setBusy(true);
    setError(null);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      setCurrent(""); setNext(""); setConfirm("");
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card icon={<LockIcon />} title="Change Password">
      <form className="s-form" onSubmit={submit} noValidate>
        <PasswordField label="Current password" value={current} onChange={setCurrent} autoComplete="current-password" />
        <PasswordField label="New password" value={next} onChange={setNext} autoComplete="new-password" />
        <PasswordField label="Confirm new password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
        {error && <div className="alert alert--error" role="alert">{error}</div>}
        {done && <div className="alert alert--ok" role="status">Password updated. Your other devices have been signed out.</div>}
        <button type="submit" className="primary s-submit" disabled={busy}>
          {busy ? "Updating…" : "Update Password"}
        </button>
      </form>
    </Card>
  );
}

/* ------------------------------------------------------------------ preferences */
function PreferencesCard() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const dark = theme === "dark";
  const toggle = () => {
    const next: Theme = dark ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };
  return (
    <Card icon={<SlidersIcon />} title="Preferences">
      <div className="pref">
        <div>
          <div className="pref__title" id="appearance-label">Appearance</div>
          <div className="pref__value">{dark ? "Dark mode" : "Light mode"}</div>
        </div>
        <button type="button" role="switch" aria-checked={dark} aria-labelledby="appearance-label"
                className={`switch ${dark ? "switch--on" : ""}`} onClick={toggle}>
          <span className="switch__knob" />
        </button>
      </div>
    </Card>
  );
}

export default function Settings({ user }: { user: User }) {
  return (
    <div className="settings">
      <ProfileCard user={user} />
      <PasswordCard />
      <PreferencesCard />
    </div>
  );
}
