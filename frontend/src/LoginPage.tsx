import { useState, type FormEvent } from "react";
import { api } from "./api";
import type { User } from "./types";
import { EyeIcon } from "./ui";
import background from "./assets/login-bg.jpg";
import logo from "./assets/cdc-logo.jpg";
import "./login.css";

export default function LoginPage({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.login({ username: username.trim(), password, remember }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login__bg" style={{ backgroundImage: `url(${background})` }} aria-hidden="true" />
      <div className="login__overlay" aria-hidden="true" />

      <main className="login__center">
        <header className="login__brand">
          <div className="login__logo"><img src={logo} alt="CDC" /></div>
          <h1 className="login__title">BOM TOOL</h1>
          <p className="login__subtitle">Spare Parts Interchangeability Record</p>
        </header>

        <form className="login__card" onSubmit={submit} noValidate>
          <h2>Welcome to CDC</h2>
          <p className="login__hint">Sign in to continue</p>

          <label className="login__field">
            <span>Username or Email</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)}
                   autoComplete="username" autoFocus required />
          </label>

          <label className="login__field">
            <span>Password</span>
            <div className="login__password">
              <input type={showPassword ? "text" : "password"} value={password}
                     onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
              <button type="button" className="login__eye" onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}>
                <EyeIcon open={showPassword} />
              </button>
            </div>
          </label>

          <label className="login__remember">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            <span>Remember this device</span>
          </label>

          {error && <div className="login__error" role="alert">{error}</div>}

          <button type="submit" className="login__submit" disabled={busy}>
            {busy ? "Signing in…" : <>Sign In <span aria-hidden="true">→</span></>}
          </button>
        </form>

        <footer className="login__footer">
          <span>Privacy Policy</span>
          <span>Terms of Service</span>
          <span>Support</span>
        </footer>
      </main>
    </div>
  );
}
