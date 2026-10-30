// History & files: a read-only browser of a project's files and their committed versions.
// The daemon lists, reads and renders the files (GET /api/project-files).
import { useEffect, useState } from "react";
import type { MouseEvent } from "react";
import { t } from "../i18n";
import { filesHash, projectHash } from "../route";
import { api, openUrl } from "../shell";
import { idOf, int, nameOf } from "../status";
import type { Project } from "../status";

type Entry = { path: string; group: string };
type Revision = { revision: string; at: string; label: string };
type Listing = { files: Entry[]; coverage: unknown[]; scope: string };
type History = { revisions: Revision[]; reason: string };
type Content = {
  group: string; bytes: number; revision: string | null; modified: number | null;
  text: string; html: string | null; preview_warning: string | null;
};

// The daemon sends English group names; the filter keys stay canonical, only the heading translates.
const GROUPS = (): [string, string][] => [
  ["Project records", t("files.projectRecords")],
  ["Archived milestone", t("files.archivedMilestone")],
  ["Repository", t("files.repository")],
];
const request = <T,>(params: Record<string, string>) => api<T>("GET", "/api/project-files?" + new URLSearchParams(params));

export function Files({ project, path }: { project: Project; path: string }) {
  const root = project.root, id = idOf(project);
  const [listing, setListing] = useState<Listing | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [content, setContent] = useState<Content | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [query, setQuery] = useState("");
  const [raw, setRaw] = useState(false);
  const [revision, setRevision] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => setRevision(""), [root, path]);
  useEffect(() => {
    let live = true;
    setBusy(true); setError(""); setContent(null);
    (async () => {
      try {
        const [files, versions] = await Promise.all([
          request<Listing>({ root, action: "list" }), request<History>({ root, path, action: "history" })]);
        if (!live) return;
        setListing(files); setHistory(versions);
        const file = await request<Content>({ root, path, action: "read", ...(revision ? { revision } : {}) });
        if (live) setContent(file);
      } catch (failure) {
        if (live) setError(String(failure));
      }
      if (live) setBusy(false);
    })();
    return () => { live = false; };
  }, [root, path, revision, reload]);

  // Links inside a document stay in this viewer; web links open in the browser.
  const follow = (event: MouseEvent) => {
    const link = (event.target as Element).closest("a");
    if (!link) return;
    event.preventDefault();
    const href = link.dataset.documentLink ?? link.getAttribute("href") ?? "";
    if (href.startsWith("#")) return;
    if (!link.dataset.documentLink) return void openUrl(href);
    const base = new URL(path, "http://project.invalid/");
    try {
      const target = new URL(href, base);
      if (target.origin === base.origin) location.hash = filesHash(id, decodeURIComponent(target.pathname.slice(1)));
    } catch { /* not a path: ignore */ }
  };

  const entries = (listing?.files ?? []).filter((file) => file.path.toLowerCase().includes(query.toLowerCase()));
  const revisions = history?.revisions ?? [];
  const preview = !raw && !!content?.html;

  return (
    <main className="page project">
      <a className="crumb" href="#/projects">‹ {t("nav.projects")}</a> <span className="sub">/</span>{" "}
      <a className="crumb" href={projectHash(id)}>{nameOf(project)}</a>
      <div className="phead"><h1 className="title">{t("projectPage.historyFiles")}</h1><span className="sub">{t("files.readOnly")} · {nameOf(project)}</span></div>
      <p className="note">{t("files.lead")}</p>
      <div className="card files">
        <aside className="files-side">
          <label htmlFor="file-search">{t("files.findAFile")}</label>
          <input id="file-search" placeholder={t("files.nameOrPath")} value={query} onChange={(event) => setQuery(event.target.value)} />
          <nav className="file-list" aria-label={t("files.projectFiles")}>
            {entries.length ? GROUPS().map(([group, label]) => {
              const files = entries.filter((file) => file.group === group);
              return files.length > 0 && <div key={group}>
                <h3>{label}</h3>
                {files.map((file) => (
                  <a key={file.path} href={filesHash(id, file.path)} aria-current={file.path === path ? "page" : undefined}>
                    {file.path.split("/").pop()}<small>{file.path.split("/").slice(0, -1).join("/") || t("files.projectRoot")}</small>
                  </a>
                ))}
              </div>;
            }) : <p className="note">{busy ? t("files.loadingFiles") : t("files.noMatching")}</p>}
          </nav>
          <p className="note">{listing?.scope}</p>
          {!!listing?.coverage.length && <>
            <p className="error">{t("files.sourcesNeedAttention", { n: listing.coverage.length })}</p>
            <details><summary>{t("files.readErrors")}</summary><pre className="json">{JSON.stringify(listing.coverage, null, 2)}</pre></details>
          </>}
        </aside>
        <section className="grow">
          <div className="file-bar">
            <div>
              <div className="mono">{path}</div>
              <div className="meta">{content ? `${content.group} · ${int(content.bytes)} ${t("files.bytes")} · ${content.revision ? t("files.committedFile")
                : content.modified ? new Date(content.modified * 1000).toLocaleString() : t("files.workingTree")}` : t("files.fileContents")}</div>
            </div>
            <div className="seg">
              <button aria-pressed={preview} disabled={!content?.html} onClick={() => setRaw(false)}>{t("skillsPage.preview")}</button>
              <button aria-pressed={!preview} onClick={() => setRaw(true)}>{t("files.raw")}</button>
            </div>
          </div>
          <div className="file-bar">
            <label htmlFor="file-revision">{t("files.version")}</label>
            <select id="file-revision" value={revision} disabled={busy} onChange={(event) => setRevision(event.target.value)}>
              <option value="">{t("files.workingTree")}</option>
              {revisions.map((item) => <option key={item.revision} value={item.revision}>{item.at} · {item.label} · {item.revision.slice(0, 7)}</option>)}
            </select>
            <button className="link" onClick={() => setReload((count) => count + 1)}>{t("files.reloadFile")}</button>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <article className="document" aria-label={t("files.fileContents")} onClick={follow}>
            {busy ? <p role="status">{t("files.loadingFile")}</p> : content && <>
              {content.preview_warning && <p className="note">{content.preview_warning}</p>}
              {/* The daemon renders Markdown with raw HTML turned off (project_files.py). */}
              {preview ? <div dangerouslySetInnerHTML={{ __html: content.html! }} /> : <pre>{content.text}</pre>}
            </>}
          </article>
          <details className="file-history">
            <summary>{t("files.gitHistory", { n: revisions.length })}</summary>
            <p className="note">{history?.reason ?? t("files.historyFailed")}</p>
            {revisions.map((item) => (
              <button key={item.revision} onClick={() => setRevision(item.revision)}>
                <span className="mono">{item.revision.slice(0, 7)}</span><span>{item.label}</span><span>{item.at}</span>
              </button>
            ))}
          </details>
        </section>
      </div>
    </main>
  );
}
