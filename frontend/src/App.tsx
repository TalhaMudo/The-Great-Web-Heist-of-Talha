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
        body: JSON.stringify({ origin, k: depth })
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
          <button onClick={startIndex} disabled={!origin || isIndexing}>
            {isIndexing ? "Starting..." : "Start Indexing"}
          </button>
          {currentJobId && <p className="hint">Active job id: {currentJobId}</p>}
        </section>

        <section className="panel">
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
              <table>
                <thead>
                  <tr>
                    <th>URL</th>
                    <th>Origin</th>
                    <th>Depth</th>
                    <th>Score</th>
                    <th>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={`${r.relevant_url}-${r.depth}`}>
                      <td>
                        <a href={r.relevant_url} target="_blank" rel="noreferrer">
                          {r.relevant_url}
                        </a>
                      </td>
                      <td>{r.origin_url}</td>
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
                <div className="jobs-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Job ID</th>
                        <th>Origin</th>
                        <th>Depth</th>
                        <th>Status</th>
                        <th>Processed</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.jobs_summary.map((job) => (
                        <tr key={job.id}>
                          <td>{job.id.slice(0, 8)}…</td>
                          <td>{job.origin_url}</td>
                          <td>{job.max_depth}</td>
                          <td>{job.status}</td>
                          <td>{job.processed_urls}</td>
                          <td>{new Date(job.created_at).toLocaleTimeString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <p className="hint">Waiting for metrics from backend…</p>
          )}
        </section>
      </main>
    </div>
  );
};

