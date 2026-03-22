import React, { useEffect, useState } from "react";

type JobSummary = {
  id: string;
  origin_url: string;
  max_depth: number;
  created_at: string;
  updated_at: string;
  status: string;
  processed_urls: number;
  queued_urls: number;
  backpressure_state: string;
  rate_limit_per_sec: number;
};

type JobEvent = {
  created_at: string;
  level: string;
  message: string;
  url?: string | null;
  depth?: number | null;
};

type JobDetail = {
  id: string;
  origin_url: string;
  max_depth: number;
  created_at: string;
  updated_at: string;
  status: string;
  error_message?: string | null;
  rate_limit_per_sec: number;
  stats: {
    processed_urls: number;
    discovered_urls: number;
    duplicate_urls: number;
    failed_urls: number;
    queued_urls: number;
    queue_max: number;
    active_workers: number;
    backpressure_state: string;
  };
  visited_count: number;
  frontier_count: number;
  frontier_preview: Array<{
    url: string;
    depth: number;
    origin_url: string;
  }>;
  recent_events: JobEvent[];
};

type Metrics = {
  processed_urls: number;
  discovered_urls: number;
  duplicate_urls: number;
  failed_urls: number;
  queued_urls: number;
  queue_max: number;
  backpressure_state: string;
  active_workers: number;
  jobs_summary: JobSummary[];
};

type SearchResult = {
  relevant_url: string;
  origin_url: string;
  depth: number;
  score?: number | null;
  title?: string | null;
};

export const App: React.FC = () => {
  const [viewMode, setViewMode] = useState<"crawler" | "search">("crawler");
  const [origin, setOrigin] = useState("");
  const [depth, setDepth] = useState(2);
  const [rateLimit, setRateLimit] = useState(1.0);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isIndexing, setIsIndexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isMutatingJob, setIsMutatingJob] = useState(false);
  const [globalQueueLimitInput, setGlobalQueueLimitInput] = useState("1000");
  const [jobRateInputs, setJobRateInputs] = useState<Record<string, string>>({});

  useEffect(() => {
    const fetchMetrics = () => {
      fetch("/metrics")
        .then((res) => res.json())
        .then((data: Metrics) => {
          setMetrics(data);
          setGlobalQueueLimitInput(String(data.queue_max));
          setJobRateInputs((prev) => {
            const next = { ...prev };
            for (const job of data.jobs_summary) {
              if (!next[job.id]) {
                next[job.id] = String(job.rate_limit_per_sec);
              }
            }
            return next;
          });
          if (!selectedJobId && data.jobs_summary.length > 0) {
            setSelectedJobId(data.jobs_summary[0].id);
          }
        })
        .catch(() => {
          /* ignore */
        });
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => clearInterval(interval);
  }, [selectedJobId]);

  useEffect(() => {
    if (!selectedJobId) {
      setSelectedJob(null);
      return;
    }
    const fetchJob = () => {
      fetch(`/jobs/${selectedJobId}`)
        .then((res) => res.json())
        .then((data: JobDetail) => setSelectedJob(data))
        .catch(() => {
          /* ignore */
        });
    };
    fetchJob();
    const interval = setInterval(fetchJob, 2000);
    return () => clearInterval(interval);
  }, [selectedJobId]);

  const startIndex = async () => {
    setError(null);
    try {
      setIsIndexing(true);
      const res = await fetch("/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, k: depth, rate_limit_per_sec: rateLimit })
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to start indexing");
      }
      const data = await res.json();
      setCurrentJobId(data.job_id);
      setSelectedJobId(data.job_id);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsIndexing(false);
    }
  };

  const runSearch = async () => {
    setError(null);
    try {
      const res = await fetch(`/search?query=${encodeURIComponent(query)}`);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Search failed");
      }
      const data = await res.json();
      setResults(data.results ?? []);
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  };

  const runFeelingLucky = async () => {
    setError(null);
    try {
      const res = await fetch(`/search?query=${encodeURIComponent(query)}`);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Search failed");
      }
      const data = await res.json();
      const nextResults: SearchResult[] = data.results ?? [];
      setResults(nextResults);
      if (nextResults.length === 0 || !nextResults[0].relevant_url) {
        throw new Error("No results found for this query.");
      }
      window.open(nextResults[0].relevant_url, "_blank", "noopener,noreferrer");
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  };

  const mutateJob = async (action: "pause" | "resume") => {
    if (!selectedJobId) {
      return;
    }
    setError(null);
    try {
      setIsMutatingJob(true);
      const res = await fetch(`/jobs/${selectedJobId}/${action}`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? `Failed to ${action} job`);
      }
      const data = await res.json();
      setSelectedJob(data);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsMutatingJob(false);
    }
  };

  const searchPanel = (
    <section className="panel panel-search">
      <h2>Search</h2>
      <label className="field">
        <span>Query</span>
        <input
          type="text"
          placeholder="search terms"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <button onClick={runSearch} disabled={!query}>
        Search Indexed Pages
      </button>
      <button onClick={runFeelingLucky} disabled={!query}>
        I'm Feeling Lucky
      </button>
      <div className="results">
        {results.length === 0 ? (
          <p className="hint">No results yet. Try searching after indexing.</p>
        ) : (
          <table className="search-table">
            <thead>
              <tr>
                <th style={{ width: "40%" }}>URL</th>
                <th style={{ width: "25%" }}>Origin</th>
                <th style={{ width: "8%" }}>Depth</th>
                <th style={{ width: "10%" }}>Score</th>
                <th style={{ width: "17%" }}>Title</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={`${r.relevant_url}-${r.depth}`}>
                  <td className="url-cell">
                    <a className="result-link" href={r.relevant_url} target="_blank" rel="noreferrer">
                      {r.relevant_url}
                    </a>
                  </td>
                  <td className="url-cell">{r.origin_url}</td>
                  <td>{r.depth}</td>
                  <td>{r.score?.toFixed(2)}</td>
                  <td>{r.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );

  return (
    <div className="app">
      <header className="header">
        <h1>The Great Web Heist of Talha</h1>
        <p>AI-assisted crawler and live search dashboard</p>
        <div className="mode-switch" role="tablist" aria-label="Application mode">
          <button
            className={`mode-btn ${viewMode === "crawler" ? "mode-btn-active" : ""}`}
            onClick={() => setViewMode("crawler")}
            role="tab"
            aria-selected={viewMode === "crawler"}
          >
            Crawler Mode
          </button>
          <button
            className={`mode-btn ${viewMode === "search" ? "mode-btn-active" : ""}`}
            onClick={() => setViewMode("search")}
            role="tab"
            aria-selected={viewMode === "search"}
          >
            Search Mode
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className={`layout ${viewMode === "search" ? "layout-search" : ""}`}>
        {viewMode === "crawler" && <div className="sidebar">
          <section className="panel">
            <h2>Index Control</h2>
            <label className="field">
              <span>Origin URL</span>
              <input
                type="url"
                placeholder="https://example.com"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Max depth (k)</span>
              <input
                type="number"
                min={0}
                max={8}
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>
                Crawler Speed (req/s)
              </span>
              <input
                type="number"
                min={0.1}
                step={0.1}
                value={rateLimit}
                onChange={(e) => setRateLimit(Number(e.target.value))}
              />
            </label>
            <button onClick={startIndex} disabled={!origin || isIndexing}>
              {isIndexing ? "Starting..." : "Start Indexing"}
            </button>
            {currentJobId && <p className="hint">Active job id: {currentJobId}</p>}
          </section>

          <section className="panel">
            <h2>System Dashboard</h2>
            <label className="field">
              <span>Global Queue Limit (all jobs combined)</span>
              <div className="inline-control">
                <input
                  type="number"
                  min={1}
                  value={globalQueueLimitInput}
                  onChange={(e) => setGlobalQueueLimitInput(e.target.value)}
                />
                <button
                  onClick={async () => {
                    setError(null);
                    try {
                      const val = Number(globalQueueLimitInput);
                      const res = await fetch("/settings/queue-limit", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ global_queue_limit: val }),
                      });
                      if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail ?? "Failed to update global queue limit");
                      }
                      const data = await res.json();
                      setMetrics(data);
                    } catch (e: any) {
                      setError(e.message ?? String(e));
                    }
                  }}
                >
                  Apply
                </button>
              </div>
            </label>
            {metrics ? (
              <>
                <div className="metrics-grid">
                  <div className="metric">
                    <span className="label">Processed URLs</span>
                    <span className="value">{metrics.processed_urls}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Discovered URLs</span>
                    <span className="value">{metrics.discovered_urls}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Duplicates Skipped</span>
                    <span className="value">{metrics.duplicate_urls}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Failed Fetches</span>
                    <span className="value">{metrics.failed_urls}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Queue depth</span>
                    <span className="value">
                      {metrics.queued_urls} / {metrics.queue_max}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="label">Backpressure</span>
                    <span className={`badge badge-${metrics.backpressure_state}`}>
                      {metrics.backpressure_state}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="label">Active workers</span>
                    <span className="value">{metrics.active_workers}</span>
                  </div>
                </div>
                <h3>Jobs</h3>
                {metrics.jobs_summary.length === 0 ? (
                  <p className="hint">No jobs yet.</p>
                ) : (
                  <div className="jobs-list">
                    {metrics.jobs_summary.map((job) => (
                      <article
                        className={`job-card ${selectedJobId === job.id ? "job-card-selected" : ""}`}
                        key={job.id}
                        onClick={() => setSelectedJobId(job.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            setSelectedJobId(job.id);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <div className="job-card-header">
                          <strong>{job.id.slice(0, 8)}…</strong>
                          <span className={`badge badge-${job.status}`}>
                            {job.status}
                          </span>
                        </div>
                        <div className="job-card-url">{job.origin_url}</div>
                        <div className="job-card-meta">
                          <span>Depth: {job.max_depth}</span>
                          <span>Processed: {job.processed_urls}</span>
                          <span>Queue: {job.queued_urls}</span>
                          <span>{new Date(job.updated_at).toLocaleTimeString()}</span>
                        </div>
                        <div className="job-card-controls">
                          <label>Req/s</label>
                          <input
                            type="number"
                            min={0.1}
                            step={0.1}
                            value={jobRateInputs[job.id] ?? String(job.rate_limit_per_sec)}
                            onChange={(e) =>
                              setJobRateInputs((prev) => ({
                                ...prev,
                                [job.id]: e.target.value,
                              }))
                            }
                            onClick={(e) => e.stopPropagation()}
                          />
                          <button
                            onClick={async (e) => {
                              e.stopPropagation();
                              setError(null);
                              try {
                                const val = Number(jobRateInputs[job.id] ?? job.rate_limit_per_sec);
                                const res = await fetch(`/jobs/${job.id}/rate-limit`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ rate_limit_per_sec: val }),
                                });
                                if (!res.ok) {
                                  const data = await res.json();
                                  throw new Error(data.detail ?? "Failed to update job rate");
                                }
                                const data = await res.json();
                                setJobRateInputs((prev) => ({ ...prev, [job.id]: String(val) }));
                                if (selectedJobId === job.id) {
                                  setSelectedJob(data);
                                }
                              } catch (err: any) {
                                setError(err.message ?? String(err));
                              }
                            }}
                          >
                            Set
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="hint">Waiting for metrics from backend…</p>
            )}
          </section>
        </div>}

        <div className={`main ${viewMode === "search" ? "main-search" : ""}`}>
          {viewMode === "crawler" && <section className="panel panel-job-detail">
            <h2>Job Detail</h2>
            {!selectedJob ? (
              <p className="hint">Select a job to inspect its live state and control it.</p>
            ) : (
              <>
                <div className="job-detail-header">
                  <div>
                    <div className="hint">Job ID</div>
                    <code>{selectedJob.id}</code>
                  </div>
                  <span className={`badge badge-${selectedJob.status}`}>
                    {selectedJob.status}
                  </span>
                </div>
                <div className="job-actions">
                  <button
                    onClick={() => mutateJob("pause")}
                    disabled={selectedJob.status !== "running" || isMutatingJob}
                  >
                    Pause Job
                  </button>
                  <button
                    onClick={() => mutateJob("resume")}
                    disabled={selectedJob.status !== "paused" || isMutatingJob}
                  >
                    Resume Job
                  </button>
                </div>
                <div className="job-detail-grid">
                  <div className="metric">
                    <span className="label">Origin</span>
                    <span className="value">{selectedJob.origin_url}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Rate Limit</span>
                    <span className="value">{selectedJob.rate_limit_per_sec.toFixed(1)} req/s</span>
                  </div>
                  <div className="metric">
                    <span className="label">Visited</span>
                    <span className="value">{selectedJob.visited_count}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Frontier</span>
                    <span className="value">{selectedJob.frontier_count}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Processed</span>
                    <span className="value">{selectedJob.stats.processed_urls}</span>
                  </div>
                  <div className="metric">
                    <span className="label">Backpressure</span>
                    <span className={`badge badge-${selectedJob.stats.backpressure_state}`}>
                      {selectedJob.stats.backpressure_state}
                    </span>
                  </div>
                </div>
                <h3>Frontier Preview</h3>
                {selectedJob.frontier_preview.length === 0 ? (
                  <p className="hint">No queued URLs.</p>
                ) : (
                  <div className="job-frontier">
                    {selectedJob.frontier_preview.map((item) => (
                      <div className="frontier-row" key={`${item.url}-${item.depth}`}>
                        <span className="frontier-depth">d={item.depth}</span>
                        <span className="frontier-url">{item.url}</span>
                      </div>
                    ))}
                  </div>
                )}
                <h3>Recent Events</h3>
                {selectedJob.recent_events.length === 0 ? (
                  <p className="hint">No events yet.</p>
                ) : (
                  <div className="job-events">
                    {selectedJob.recent_events.map((event, idx) => (
                      <div className="event-row" key={`${event.created_at}-${idx}`}>
                        <span className={`badge badge-${event.level === "error" ? "queue_full" : "normal"}`}>
                          {event.level}
                        </span>
                        <span className="event-message">{event.message}</span>
                        {event.url && <span className="event-url">{event.url}</span>}
                        <span className="hint">{new Date(event.created_at).toLocaleTimeString()}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>}

          {viewMode === "search" && searchPanel}
        </div>
      </main>
    </div>
  );
};

