### Technologies and design choices

#### Python backend and concurrency model

The backend is a single Python process exposing a HTTP API using FastAPI. The crawler uses **`asyncio`** for concurrency: we maintain an `asyncio.Queue` of crawl tasks and run a fixed number of worker tasks that pull from this queue. Each worker performs blocking network I/O (`urllib.request.urlopen`) inside `loop.run_in_executor`, so we keep the event loop responsive while still using standard-library HTTP primitives. This design gives us a clear concurrency story: the queue represents work to be done, the workers represent parallelism, and backpressure is implemented by giving the queue a `maxsize`.

#### Indexing and “never visit twice”

For each crawl job we maintain a **visited set** of normalized URLs inside the crawler context. Normalization combines relative links with the base URL, strips fragments (so `#section` links are not treated as separate pages), and filters to `http`/`https` schemes. Before fetching a page, the worker checks this set; if the URL is already present, the page is skipped. This ensures that within a job we never crawl the same page twice, even if it appears in many places in the link graph. After fetching HTML, we use a small `HTMLParser` subclass to collect `<a href="...">` links; new, unseen links are pushed into the queue with an incremented `depth`, but only if the depth is still ≤ `k`.

#### Backpressure and rate limiting

Backpressure is handled in two layers. First, the crawl queue itself is **bounded**: `asyncio.Queue(maxsize=N)`. When workers discover many new links faster than they can fetch them, attempts to `put_nowait` into a full queue raise `QueueFull`. When that happens we mark the job and global `backpressure_state` as `"queue_full"` and stop enqueueing additional links until the queue drains, which the UI displays as a yellow warning badge. Second, we implement a simple **global rate limiter**: before each request, a worker checks how much time has passed since the last HTTP request and sleeps if needed to keep the average request rate below a configurable `rate_limit_per_sec`. This prevents the crawler from overwhelming a target site and makes its behavior easier to reason about in class.

#### Search index and relevancy heuristic

The search index is an in-memory **inverted index** built from page titles and visible text. An `HTMLParser` subclass collects `<title>` content and text nodes, which we tokenize using a regular expression that extracts alphanumeric words, lowercases them, and discards punctuation. For each page we count how many times each token appears and then insert `(url, origin_url, depth, score)` entries into a dictionary keyed by token, where `score` is the term frequency on that page. To serve a query, we tokenize the query string, look up the postings lists for each token, sum the scores per URL, and sort descending. This is a deliberately simple and transparent heuristic so you can easily explain in a presentation why a URL appears high or low in the results.

#### Persistence and partial resume behavior

To survive restarts, we use **SQLite via the Python standard library** (`sqlite3`). Each indexed page is saved into a `pages` table with columns `(url, origin_url, depth, title, body_snippet)`, where `body_snippet` contains a truncated bag-of-words representation of the page. Crawl jobs are stored in a `jobs` table with their id, origin, depth, creation time, and status. On startup, the backend initializes the database (creating tables if needed), loads all stored pages, and rebuilds the in-memory inverted index via an `add_snapshot_page` method that does not re-write to the database. It also reloads historical jobs into the crawler service so the UI can show past runs. We do not resume in-flight queues from the exact point of interruption, but we **do** preserve all already-indexed pages and their searchability across restarts, which is the most useful part of resume behavior for this project.

#### React UI and system visibility

The frontend is built with **Vite + React + TypeScript**. The UI has three main panels: an Index Control panel, a Search panel, and a System Dashboard. The dashboard polls `/metrics` every few seconds and visualizes processed URL count, queue depth versus `queue_max`, current backpressure state, and active worker count, along with a summarized job table. This gives you a live, visual way to talk about concurrency and backpressure while the crawler runs. Styling is done with a single `styles.css` file that uses a dark, gradient background similar to the lecture slides, with card-like panels for readability. API calls are made with the browser `fetch` API, and Vite’s dev server proxies `/index`, `/search`, `/metrics`, and `/jobs` to the Python backend on `localhost:8000`.

