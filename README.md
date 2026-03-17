### The Great Web Heist of Talha

This repository contains a small, AI-assisted **web crawler and search engine** built for the BLG 483E Artificial Intelligence Aided Computer Engineering course. The system consists of a Python backend that crawls and indexes pages plus a React dashboard that lets you start crawls, run searches, and watch system metrics (queue depth, processed URLs, backpressure state) in real time.

#### Running the backend

1. Create and activate a virtualenv (optional but recommended).
2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the backend on `localhost:8000`:

   ```bash
   uvicorn backend.app:app --reload
   ```

#### Running the frontend

1. Install Node dependencies:

   ```bash
   cd frontend
   npm install
   ```

2. Start the React dev server on `localhost:5173`:

   ```bash
   npm run dev
   ```

3. Open the printed URL in your browser. Use the **Index Control** panel to start a crawl, then use the **Search** and **System Dashboard** panels to explore the index and view runtime metrics.

