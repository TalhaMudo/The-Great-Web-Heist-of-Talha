import React, { useEffect, useState } from "react";

type JobSummary = {
  id: string;
  origin_url: string;
  max_depth: number;
  max_urls_to_visit?: number | null;
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
  max_urls_to_visit?: number | null;
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

type EmbeddingStatus = {
  updated_at: string;
  status: string;
  model_name: string;
  rate_limit_per_sec: number;
  max_pages?: number | null;
  total_pages: number;
  embedded_pages: number;
  failed_pages: number;
  remaining_pages: number;
  progress_percent: number;
  error_message?: string | null;
};

export const App: React.FC = () => {
  const [viewMode, setViewMode] = useState<"crawler" | "search" | "embeddings">("crawler");
  const [origin, setOrigin] = useState("");
  const [depth, setDepth] = useState(2);
  const [maxUrlsToVisit, setMaxUrlsToVisit] = useState("500");
  const [rateLimit, setRateLimit] = useState(1.0);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [query, setQuery] = useState("");
  const [classicResults, setClassicResults] = useState<SearchResult[]>([]);
  const [semanticResults, setSemanticResults] = useState<SearchResult[]>([]);
  const [isIndexing, setIsIndexing] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isMutatingJob, setIsMutatingJob] = useState(false);
  const [globalQueueLimitInput, setGlobalQueueLimitInput] = useState("1000");
  const [jobRateInputs, setJobRateInputs] = useState<Record<string, string>>({});
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [embeddingRateLimit, setEmbeddingRateLimit] = useState("1.0");
  const [embeddingMaxPages, setEmbeddingMaxPages] = useState("500");
  const [isMutatingEmbeddingJob, setIsMutatingEmbeddingJob] = useState(false);

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

  useEffect(() => {
    const fetchEmbeddingStatus = () => {
      fetch("/embeddings/status")
        .then((res) => res.json())
        .then((data: EmbeddingStatus) => {
          setEmbeddingStatus((prev) => {
            if (prev === null) {
              setEmbeddingRateLimit(String(data.rate_limit_per_sec));
            }
            return data;
          });
        })
        .catch(() => {
          /* ignore */
        });
    };
    fetchEmbeddingStatus();
    const interval = setInterval(fetchEmbeddingStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  const startIndex = async () => {
    setError(null);
    try {
      setIsIndexing(true);
      const res = await fetch("/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin,
          k: depth,
          max_urls_to_visit: maxUrlsToVisit ? Number(maxUrlsToVisit) : null,
          rate_limit_per_sec: rateLimit,
        }),
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

  const runSearch = async (): Promise<{ classic: SearchResult[]; semantic: SearchResult[] }> => {
    setError(null);
    setIsSearching(true);
    try {
      const [classicRes, semanticRes] = await Promise.all([
        fetch(`/search?query=${encodeURIComponent(query)}`),
        fetch(`/search/semantic?query=${encodeURIComponent(query)}`),
      ]);
      if (!classicRes.ok || !semanticRes.ok) {
        const data = classicRes.ok ? await semanticRes.json() : await classicRes.json();
        throw new Error(data.detail ?? "Search failed");
      }
      const [classicData, semanticData] = await Promise.all([classicRes.json(), semanticRes.json()]);
      const classic = classicData.results ?? [];
      const semantic = semanticData.results ?? [];
      setClassicResults(classic);
      setSemanticResults(semantic);
      return { classic, semantic };
    } catch (e: any) {
      setError(e.message ?? String(e));
      return { classic: [], semantic: [] };
    } finally {
      setIsSearching(false);
    }
  };

  const runFeelingLucky = async () => {
    setError(null);
    try {
      const searched = await runSearch();
      if (searched.classic.length === 0) {
        throw new Error("No results found for this query.");
      }
      const randomIdx = Math.floor(Math.random() * searched.classic.length);
      const lucky = searched.classic[randomIdx];
      if (!lucky?.relevant_url) {
        throw new Error("No valid URL found in search results.");
      }
      window.open(lucky.relevant_url, "_blank", "noopener,noreferrer");
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

  const startEmbedding = async () => {
    setError(null);
    try {
      setIsMutatingEmbeddingJob(true);
      const res = await fetch("/embeddings/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rate_limit_per_sec: Number(embeddingRateLimit),
          max_pages: embeddingMaxPages ? Number(embeddingMaxPages) : null,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to start embedding engine");
      }
      const status: EmbeddingStatus = await res.json();
      setEmbeddingStatus(status);
      setEmbeddingRateLimit(String(status.rate_limit_per_sec));
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsMutatingEmbeddingJob(false);
    }
  };

  const pauseEmbedding = async () => {
    setError(null);
    try {
      setIsMutatingEmbeddingJob(true);
      const res = await fetch("/embeddings/pause", { method: "POST" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to pause embedding engine");
      }
      const status: EmbeddingStatus = await res.json();
      setEmbeddingStatus(status);
      setEmbeddingRateLimit(String(status.rate_limit_per_sec));
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsMutatingEmbeddingJob(false);
    }
  };

  const updateEmbeddingRateLimit = async () => {
    setError(null);
    try {
      setIsMutatingEmbeddingJob(true);
      const res = await fetch("/embeddings/rate-limit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rate_limit_per_sec: Number(embeddingRateLimit) }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to update embedding speed");
      }
      const status: EmbeddingStatus = await res.json();
      setEmbeddingStatus(status);
      setEmbeddingRateLimit(String(status.rate_limit_per_sec));
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsMutatingEmbeddingJob(false);
    }
  };

  const clearAllEmbeddings = async () => {
    const confirmed = window.confirm(
      "Are you sure you want to delete all embeddings? This cannot be undone and semantic search will be empty until you embed again."
    );
    if (!confirmed) {
      return;
    }
    setError(null);
    try {
      setIsMutatingEmbeddingJob(true);
      const res = await fetch("/embeddings/clear", { method: "POST" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Failed to clear embeddings");
      }
      const status: EmbeddingStatus = await res.json();
      setEmbeddingStatus(status);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setIsMutatingEmbeddingJob(false);
    }
  };

  const searchPanel = (
    <section className="panel panel-search panel-search-upgraded">
      <div className="search-header">
        <h2>
          <span className="search-icon" aria-hidden="true">
            🔎
          </span>{" "}
          Search
        </h2>
        <p className="search-subtitle">Find relevant URLs in pages already indexed by active or finished crawlers.</p>
      </div>
      <label className="field">
        <span>Query</span>
        <input
          className="search-input"
          type="text"
          placeholder="search terms"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="search-actions">
        <button onClick={runSearch} disabled={!query || isSearching}>
          Search Indexed Pages
        </button>
        <button className="button-secondary" onClick={runFeelingLucky} disabled={!query || isSearching}>
          I'm Feeling Lucky
        </button>
      </div>
      <div className="dual-results-grid">
        <div className="results-panel">
          <h3>Classical Search</h3>
          <div className="results">
            {classicResults.length === 0 ? (
              <p className="hint">No classical results yet.</p>
            ) : (
              <table className="search-table">
                <thead>
                  <tr>
                    <th style={{ width: "45%" }}>URL</th>
                    <th style={{ width: "20%" }}>Origin</th>
                    <th style={{ width: "8%" }}>Depth</th>
                    <th style={{ width: "10%" }}>Score</th>
                    <th style={{ width: "17%" }}>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {classicResults.map((r) => (
                    <tr key={`classic-${r.relevant_url}-${r.depth}`}>
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
        </div>
        <div className="results-panel">
          <h3>Semantic Search</h3>
          <div className="results">
            {semanticResults.length === 0 ? (
              <p className="hint">No semantic results yet. Run the embedding engine first.</p>
            ) : (
              <table className="search-table">
                <thead>
                  <tr>
                    <th style={{ width: "45%" }}>URL</th>
                    <th style={{ width: "20%" }}>Origin</th>
                    <th style={{ width: "8%" }}>Depth</th>
                    <th style={{ width: "10%" }}>Similarity</th>
                    <th style={{ width: "17%" }}>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {semanticResults.map((r) => (
                    <tr key={`semantic-${r.relevant_url}-${r.depth}`}>
                      <td className="url-cell">
                        <a className="result-link" href={r.relevant_url} target="_blank" rel="noreferrer">
                          {r.relevant_url}
                        </a>
                      </td>
                      <td className="url-cell">{r.origin_url}</td>
                      <td>{r.depth}</td>
                      <td>{r.score?.toFixed(4)}</td>
                      <td>{r.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </section>
  );

  const embeddingsPanel = (
    <section className="panel panel-embeddings">
      <h2>Embeddings Control</h2>
      <p className="search-subtitle">
        Generate semantic embeddings manually from already crawled pages with your selected speed and limit.
      </p>
      <div className="embedding-control-grid">
        <label className="field">
          <span>Model</span>
          <input type="text" value="all-MiniLM-L6-v2" readOnly />
        </label>
        <label className="field">
          <span>Embedding speed (pages/s)</span>
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={embeddingRateLimit}
            onChange={(e) => setEmbeddingRateLimit(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Max pages this run</span>
          <input
            type="number"
            min={1}
            value={embeddingMaxPages}
            onChange={(e) => setEmbeddingMaxPages(e.target.value)}
          />
        </label>
      </div>
      <div className="search-actions">
        <button onClick={startEmbedding} disabled={isMutatingEmbeddingJob}>
          {embeddingStatus?.status === "running" ? "Embedding..." : "Start Embedding"}
        </button>
        <button
          className="button-secondary"
          onClick={pauseEmbedding}
          disabled={!embeddingStatus || embeddingStatus.status !== "running" || isMutatingEmbeddingJob}
        >
          Pause
        </button>
        <button className="button-secondary" onClick={updateEmbeddingRateLimit} disabled={isMutatingEmbeddingJob}>
          Update Speed
        </button>
        <button className="button-secondary" onClick={clearAllEmbeddings} disabled={isMutatingEmbeddingJob}>
          Delete All Embeddings
        </button>
      </div>
      <div className="metrics-grid">
        <div className="metric">
          <span className="label">Embedding status</span>
          <span className={`badge badge-${embeddingStatus?.status ?? "idle"}`}>{embeddingStatus?.status ?? "idle"}</span>
        </div>
        <div className="metric">
          <span className="label">Current progress</span>
          <span className="value">
            {embeddingStatus ? `${embeddingStatus.progress_percent.toFixed(1)}% of your sites are embedded` : "Loading..."}
          </span>
          <div className="progress-track" aria-label="Embedding progress">
            <div
              className="progress-fill"
              style={{ width: `${Math.min(100, Math.max(0, embeddingStatus?.progress_percent ?? 0))}%` }}
            />
          </div>
        </div>
        <div className="metric">
          <span className="label">Embedded pages</span>
          <span className="value">{embeddingStatus?.embedded_pages ?? 0}</span>
        </div>
        <div className="metric">
          <span className="label">Remaining pages</span>
          <span className="value">{embeddingStatus?.remaining_pages ?? 0}</span>
        </div>
        <div className="metric">
          <span className="label">Total crawled pages</span>
          <span className="value">{embeddingStatus?.total_pages ?? 0}</span>
        </div>
        <div className="metric">
          <span className="label">Failed this run</span>
          <span className="value">{embeddingStatus?.failed_pages ?? 0}</span>
        </div>
      </div>
      {embeddingStatus?.error_message && <p className="hint">Embedding engine error: {embeddingStatus.error_message}</p>}
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
          <button
            className={`mode-btn ${viewMode === "embeddings" ? "mode-btn-active" : ""}`}
            onClick={() => setViewMode("embeddings")}
            role="tab"
            aria-selected={viewMode === "embeddings"}
          >
            Embeddings
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className={`layout ${viewMode !== "crawler" ? "layout-search" : ""}`}>
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
              <span>Max URLs to Visit</span>
              <input
                type="number"
                min={1}
                value={maxUrlsToVisit}
                onChange={(e) => setMaxUrlsToVisit(e.target.value)}
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
                          <span>Max URLs: {job.max_urls_to_visit ?? "unbounded"}</span>
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

        <div className={`main ${viewMode !== "crawler" ? "main-search" : ""}`}>
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
                    <span className="label">Max URLs</span>
                    <span className="value">{selectedJob.max_urls_to_visit ?? "unbounded"}</span>
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
          {viewMode === "embeddings" && embeddingsPanel}
        </div>
      </main>
    </div>
  );
};

