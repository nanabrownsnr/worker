import React, { useCallback, useState } from "react";
import { useApp, useDocumentTheme, useHostFonts, useHostStyleVariables } from "@modelcontextprotocol/ext-apps/react";

function Dot({ state }) { return <span className={"dot " + (state || "queued")} aria-label={state} />; }

export default function App() {
  const [tasks, setTasks] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const onAppCreated = useCallback((createdApp) => {
    console.info("[developer-tasks] MCP App created", createdApp);
    createdApp.ontoolresult = (result) => {
      console.info("[developer-tasks] tool result received", result);
      const data = result?.structuredContent;
      console.info("[developer-tasks] structured content", data);
      if (Array.isArray(data?.tasks)) {
        console.info("[developer-tasks] rendering tasks", data.tasks.length);
        setTasks(data.tasks);
      }
      if (data?.job) {
        console.info("[developer-tasks] rendering task detail", data.job.job_id);
        setSelected(data.job);
      }
      setError(data?.error || null);
    };
  }, []);
  const { app, isConnected, error: connectionError } = useApp({
    appInfo: { name: "developer-tasks", version: "1.0.0" },
    capabilities: {},
    onAppCreated,
    autoResize: true,
  });
  console.info("[developer-tasks] render state", {
    isConnected,
    hasApp: Boolean(app),
    connectionError: connectionError?.message || null,
  });
  useHostStyleVariables(app, app?.getHostContext());
  useHostFonts(app, app?.getHostContext());
  const theme = useDocumentTheme();

  async function refreshTasks() {
    if (!app) return;
    setError(null);
    try {
      const result = await app.callServerTool({ name: "get_tasks", arguments: { limit: 50 } });
      const data = result?.structuredContent;
      if (Array.isArray(data?.tasks)) setTasks(data.tasks);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load tasks"); }
  }
  async function openTask(taskId) {
    if (!app) return;
    try {
      const result = await app.callServerTool({ name: "get_task", arguments: { task_id: taskId } });
      const data = result?.structuredContent;
      if (data?.job) setSelected(data.job);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load task"); }
  }

  return <main className="card" data-host-theme={theme}>
    <div className="header"><div><p className="eyebrow">Developer</p><h1>{selected ? "Task details" : "Tasks"}</h1></div><button onClick={selected ? () => setSelected(null) : refreshTasks} disabled={!isConnected}>{selected ? "Back" : "Refresh"}</button></div>
    {connectionError && <p className="error">{connectionError.message}</p>}
    {error && <p className="error">{error}</p>}
    {selected ? <section className="task-detail">
      <div className="status"><Dot state={selected.state} /><strong>{selected.status}</strong><span className="stage">{selected.stage}</span></div>
      <div className="detail-grid">
        <div><label>Task ID</label><code>{selected.job_id}</code></div>
        <div><label>Repository</label><span>{selected.repo_url}</span></div>
        <div><label>Created</label><span>{selected.created_at}</span></div>
        <div><label>Updated</label><span>{selected.updated_at}</span></div>
        <div><label>Attempt</label><span>{selected.attempt_number}</span></div>
        <div><label>Validation returns</label><span>{selected.return_count}/{selected.max_returns}</span></div>
        {selected.working_branch && <div><label>Working branch</label><code>{selected.working_branch}</code></div>}
      </div>
      {selected.prompt && <div className="prompt"><label>Prompt</label><p>{selected.prompt}</p></div>}
      {selected.result && <><label>Result</label><pre>{JSON.stringify(selected.result.final_result || selected.result, null, 2)}</pre></>}
    </section> : <section className="task-list">{tasks.length ? tasks.map((task) => <button className="task" key={task.job_id} onClick={() => openTask(task.job_id)}><Dot state={task.state} /><span><strong>{task.status}</strong><small>{task.repo_url}</small><small><code>{task.job_id}</code></small></span></button>) : <p className="empty">{isConnected ? "Call get_tasks to load tasks." : "Connecting to MCP client..."}</p>}</section>}
  </main>;
}
