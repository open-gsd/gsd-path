// Setup, step 2: the agents that get Path skills.
import { t } from "../i18n";
import { agentCards } from "../setup";
import type { HostInfo } from "../skills";

export function SetupAgents({ hosts, selected, onToggle }: { hosts: HostInfo[]; selected: string[]; onToggle: (id: string) => void }) {
  const cards = agentCards(hosts, selected);
  return <>
    <h1 className="title">{t("setupAgents.title")}</h1>
    <p className="lead setup-lead">
      {t("setupAgents.lead", { found: cards.filter((card) => card.found).length, total: cards.length })}
      {t("setupAgents.lead2")}
    </p>
    <div className="sk-agents">
      {cards.map((card) => (
        <label key={card.id} className={`sk-agent${card.on ? " on" : ""}${card.found ? "" : " missing"}`}>
          <input type="checkbox" checked={card.on} onChange={() => onToggle(card.id)} />
          <span><b>{card.name}</b><small>{card.note}</small></span>
        </label>
      ))}
    </div>
    <p className="note">{t("setupAgents.notFoundNote")}</p>
  </>;
}
