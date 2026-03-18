import React, { useEffect, useState } from "react";

type JobSummary = {
  id: string;
  origin_url: string;
  max_depth: number;
  created_at: string;
  status: string;
  processed_urls: number;
};

type Metrics = {
  processed_urls: number;
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
  const [origin, setOrigin] = useState("");
  const [depth, setDepth] = useState(2);
  const [rateLimit, setRateLimit] = useState(1.0);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isIndexing, setIsIndexing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      fetch("/metrics")
        .then((res) => res.json())
        .then((data: Metrics) => setMetrics(data))
        .catch(() => {
          /* ignore */
        });
    }, 2000);
    return () => clearInterval(interval);
  }, []);

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

  return (
    <div className="app">
      <header className="header">
        <h1>The Great Web Heist of Talha</h1>
        <p>AI-assisted crawler and live search dashboard</p>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <main className="layout">
        <div className="sidebar">
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
                Crawl speed (requests/sec): <strong>{rateLimit.toFixed(1)}</strong>
              </span>
              <input
                type="range"
                min={0.2}
                max={3}
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
            {metrics ? (
              <>
                <div className="metrics-grid">
                  <div className="metric">
                    <span className="label">Processed URLs</span>
                    <span className="value">{metrics.processed_urls}</span>
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
                      <article className="job-card" key={job.id}>
                        <div className="job-card-header">
                          <strong>{job.id.slice(0, 8)}…</strong>
                          <span className={`badge badge-${job.status === "running" ? "normal" : "idle"}`}>
                            {job.status}
                          </span>
                        </div>
                        <div className="job-card-url">{job.origin_url}</div>
                        <div className="job-card-meta">
                          <span>Depth: {job.max_depth}</span>
                          <span>Processed: {job.processed_urls}</span>
                          <span>{new Date(job.created_at).toLocaleTimeString()}</span>
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
        </div>

        <div className="main">
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
        </div>
      </main>
    </div>
  );
};

