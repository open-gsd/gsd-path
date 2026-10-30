// Settings → App: launch at login, appearance, language, setup, diagnostics.
import { useEffect, useState } from "react";
import { setLanguage, storedLanguage, t } from "../i18n";
import type { LanguageChoice } from "../i18n";
import { api, openLogs, setAutostart } from "../shell";
import type { Shell } from "../shell";
import { setTheme, storedTheme } from "../theme";
import type { Theme } from "../theme";
import { Field, Toggle } from "./SettingsParts";

const THEMES = (): [Theme, string][] => [["system", t("theme.system")], ["light", t("theme.light")], ["dark", t("theme.dark")]];
// The language names always show in their own language, so a reader can find theirs.
const LANGUAGES = (): [LanguageChoice, string][] => [["system", t("language.system")], ["en", "English"], ["zh-CN", "简体中文"]];
type Diagnostics = { daemon_version?: string; [key: string]: unknown };

export function AppTab({ shell }: { shell: Shell }) {
  // The shell event updates `shell.autostart`; the answer of the call shows first.
  const [login, setLogin] = useState(shell.autostart);
  const [loginBusy, setLoginBusy] = useState(false);
  const [theme, setChoice] = useState(storedTheme);
  const [language, setLanguageChoice] = useState(storedLanguage);
  const [version, setVersion] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const fail = (key: string) => (reason: unknown) => setErrors((old) => ({ ...old, [key]: String(reason) }));
  const clear = (key: string) => setErrors((old) => ({ ...old, [key]: "" }));

  useEffect(() => setLogin(shell.autostart), [shell.autostart]);
  useEffect(() => {
    api<Diagnostics>("GET", "/api/diagnostics").then((report) => setVersion(report.daemon_version ?? null), fail("version"));
  }, [shell.port]);

  const toggleLogin = async (enabled: boolean) => {
    setLoginBusy(true); clear("login");
    await setAutostart(enabled).then((next) => setLogin(next.autostart), fail("login"));
    setLoginBusy(false);
  };
  const choose = (choice: Theme) => { setTheme(choice); setChoice(choice); };
  const chooseLanguage = (choice: LanguageChoice) => { setLanguage(choice); setLanguageChoice(choice); };
  const again = () => { localStorage.removeItem("gsd-path.setup-done"); location.reload(); };
  const copyReport = async () => {
    clear("report");
    try {
      await navigator.clipboard.writeText(JSON.stringify(await api<Diagnostics>("GET", "/api/diagnostics"), null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (reason) { fail("report")(reason); }
  };
  const problem = (key: string, lead: string) => errors[key] && <div className="error set-problem" role="alert">{lead} {errors[key]}</div>;

  return (
    <>
      <h2 className="set-h2">{t("settings.tab.app")}</h2>
      <div className="card set-card">
        <Field name={t("app.launchAtLogin")} hint={t("app.launchAtLoginHint")}>
          <Toggle on={login} label={t("app.launchAtLogin")} disabled={loginBusy} onChange={toggleLogin} />
        </Field>
        {problem("login", t("app.launchFailed"))}
        <Field name={t("app.appearance")} hint={t("app.appearanceHint")}>
          <div className="seg" role="group" aria-label={t("app.appearance")}>
            {THEMES().map(([value, label]) => <button key={value} aria-pressed={theme === value} onClick={() => choose(value)}>{label}</button>)}
          </div>
        </Field>
        <Field name={t("app.language")} hint={t("app.languageHint")}>
          <div className="seg" role="group" aria-label={t("app.language")}>
            {LANGUAGES().map(([value, label]) => <button key={value} aria-pressed={language === value} onClick={() => chooseLanguage(value)}>{label}</button>)}
          </div>
        </Field>
        <Field name={t("app.setup")} hint={t("app.setupHint")}>
          <button className="btn small" onClick={again}>{t("app.runSetupAgain")}</button>
        </Field>
        <Field name={t("app.diagnostics")} hint={t("app.diagnosticsHint")}>
          <button className="btn small" onClick={() => { clear("logs"); openLogs().catch(fail("logs")); }}>{t("app.openLogs")}</button>
          <button className="btn small" onClick={copyReport}>{copied ? t("ui.copied") : t("app.copyReport")}</button>
        </Field>
        {problem("logs", t("app.logsFailed"))}
        {problem("report", t("app.reportFailed"))}
      </div>
      <p className="note">
        {version ? <>{t("app.monitorVersion")} <span className="mono">{version}</span></>
          : errors.version ? t("app.monitorVersionUnavailable", { error: errors.version }) : t("app.readingVersion")}
        {" · "}{t("app.port")} <span className="mono">{shell.port}</span>
      </p>
    </>
  );
}
