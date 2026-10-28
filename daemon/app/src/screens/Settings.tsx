// Settings: a tab list on the left (Updates, Path settings, Monitoring, Usage and prices, App) and one tab on the right.
import { t } from "../i18n";
import { settingsHash } from "../route";
import type { SettingsTab } from "../route";
import type { Shell } from "../shell";
import type { Status } from "../status";
import { AppTab } from "./SettingsApp";
import { MonitoringTab, UsageTab, useConfigForm } from "./SettingsConfig";
import { PathTab } from "./SettingsPath";
import { UpdatesTab } from "./SettingsUpdates";
import "./settings.css";

const TABS = (): [SettingsTab, string][] => [
  ["updates", t("settings.tab.updates")], ["path", t("settings.tab.path")], ["monitoring", t("settings.tab.monitoring")],
  ["usage", t("settings.tab.usage")], ["app", t("settings.tab.app")]];

export function Settings({ shell, status, tab }: { shell: Shell; status: Status | null; tab: SettingsTab }) {
  // Monitoring and Usage share one form: an unsaved edit survives a change of tab.
  const form = useConfigForm(status);
  return (
    <main className="page settings">
      <h1 className="title">{t("settings.title")}</h1>
      <div className="set-layout">
        <nav className="set-nav" aria-label={t("settings.sections")}>
          {TABS().map(([key, label]) => <a key={key} href={settingsHash(key)} aria-current={tab === key ? "page" : undefined}>{label}</a>)}
        </nav>
        <section className="set-body">
          {tab === "updates" ? <UpdatesTab shell={shell} status={status} />
            : tab === "path" ? <PathTab status={status} />
            : tab === "monitoring" ? <MonitoringTab form={form} />
            : tab === "usage" ? <UsageTab form={form} />
            : <AppTab shell={shell} />}
        </section>
      </div>
    </main>
  );
}
