Crawler Project

This project implements a single-machine web crawler and keyword search engine with a live dashboard. It is designed to satisfy the assignment requirements around:

- indexing from an origin URL up to depth `k`,
- avoiding duplicate page visits,
- running search while indexing is active,
- managing load with backpressure and rate limiting,
- exposing simple controls and observability in a UI,
- and supporting resume after interruption.

The system has two major parts:

- **Crawler service**: creates and runs crawl jobs, supports pause/resume, tracks queue and worker state, and persists job state.
- **Search service**: keeps classic keyword ranking and semantic vector ranking side by side, and answers queries with relevant URLs and metadata.

## What The System Does

### 1) Indexing

When you submit an indexing request (`origin`, `k`), the backend creates a crawl job and starts worker tasks.

- URL normalization resolves relative links, removes fragments, and keeps only `http`/`https`.
- Each job tracks `visited` URLs to ensure the same URL is not fetched twice.
- Discovered links are enqueued with incremented depth until `depth <= k`.

### 2) Search

Search exposes two modes over indexed pages: classic term search and semantic vector search.

- Classic tokenization is regex-based and case-insensitive.
- Semantic search uses `all-MiniLM-L6-v2` embeddings generated from crawled page snapshots.
- Results include `relevant_url`, `origin_url`, and `depth` (plus score/title for UI visibility).
- Both search modes are available while crawlers are still running, so newly indexed pages appear as they are discovered.
- `I'm Feeling Lucky` picks a **random** result from matches and opens it.

### 3) Runtime Controls and Visibility

The dashboard allows:

- creating crawl jobs,
- pausing and resuming existing jobs,
- changing **global queue limit** across all jobs,
- changing **per-job request rate** live from each job card,
- starting, pausing, and resuming **embedding jobs** with configurable embed speed and max-page limit,
- inspecting detailed job state (frontier preview, counters, recent events),
- viewing global metrics (processed/discovered/duplicates/failed, queue pressure, workers),
- viewing embedding progress metrics (embedded/remaining/failed and `% embedded`).

## Architecture Summary

- **Backend**: FastAPI + asyncio + standard library networking (`urllib`) + SQLite persistence.
- **Frontend**: React + TypeScript + Vite.
- **Persistence**:
  - `pages` table for indexed page snapshots,
  - `jobs` table for job metadata and counters,
  - `job_visited` and `job_frontier` for resumable crawl state,
  - `job_events` for job timeline details,
  - `page_embeddings` for semantic vectors,
  - `embedding_jobs` for resumable embedding job state.

## API Endpoints

### Index/Search

- `POST /index`  
  Starts a new crawl job with origin URL, depth `k`, and optional initial rate limit.

- `GET /search?query=...&limit=...`  
  Returns relevant indexed URLs.

- `GET /search/semantic?query=...&limit=...`  
  Returns semantic nearest-neighbor matches over embedded pages.

### Job Control and Details

- `GET /jobs/{job_id}`  
  Full job detail: status, counters, frontier preview, and recent events.

- `POST /jobs/{job_id}/pause`  
  Pauses a running job.

- `POST /jobs/{job_id}/resume`  
  Resumes a paused job.

- `POST /jobs/{job_id}/rate-limit`  
  Updates a job's request rate (`req/s`) while running.

### Global Operations

- `GET /metrics`  
  Global metrics plus jobs summary.

- `POST /settings/queue-limit`  
  Updates the **global** queue limit shared by all jobs.

### Embeddings

- `POST /embeddings/jobs/start`  
  Starts a manual embedding job with configurable speed and max-page scope.

- `GET /embeddings/jobs`  
  Lists embedding jobs and progress.

- `GET /embeddings/jobs/{job_id}`  
  Returns full embedding job status and counters.

- `POST /embeddings/jobs/{job_id}/pause`  
  Pauses a running embedding job.

- `POST /embeddings/jobs/{job_id}/resume`  
  Resumes a paused embedding job.

- `POST /embeddings/jobs/{job_id}/rate-limit`  
  Updates embedding speed (`pages/s`) for a job.

## Backpressure and Load Management

The crawler enforces load control using:

- a **global queue capacity** shared across all jobs,
- per-job request-rate throttling (`req/s`),
- live backpressure state (`normal`, `high`, `queue_full`) shown in UI.

This helps keep the system stable under concurrent crawls on a single machine.

## How To Run

## Backend

```bash
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Runs on `http://127.0.0.1:8000`.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed Vite URL (usually `http://127.0.0.1:5173`).

## Suggested Demo Flow

1. Start one crawler from a seed URL with depth `k`.
2. Observe queue depth, worker count, and backpressure in dashboard.
3. Start a second crawler to demonstrate concurrent jobs.
4. Update global queue limit and per-job req/s live.
5. Pause and resume one job.
6. Open Embeddings mode and start a manual embedding run with speed/limit.
7. Run Search and compare Classical vs Semantic result tables.
8. Click a crawler job card and inspect frontier preview + event timeline.

## Limitations (Current Scope)

- Semantic quality depends on currently stored page snippets and embedding coverage.
- Single-process deployment (no horizontal scaling).
- No robots.txt policy enforcement yet.
- No hard per-domain crawl budget yet.

## Production Next Steps

To productionize this system, the first step is to separate responsibilities into independent services: crawl scheduler, crawl workers, indexing pipeline, and query API. The current asyncio loop can evolve into a worker template that pulls tasks from a durable queue and writes normalized page documents to persistent storage. The in-memory inverted index should be replaced with a dedicated search layer (for example BM25-capable engine) to improve ranking quality, scalability, and operational resilience.

Operationally, internet-facing crawling needs stronger safety controls: robots.txt compliance, per-domain throttling and crawl budgets, better failure isolation, and kill switches for runaway jobs. The persistence layer should move from local SQLite to managed, replicated data stores. Finally, add full observability (metrics, logs, traces), authentication/authorization for APIs, and deployment automation to support repeatable, safe releases.

