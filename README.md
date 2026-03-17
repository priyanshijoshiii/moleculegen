# MolGen

MolGen is a split full-stack molecular generation project:

- `frontend/` -> Next.js app (deploy to Vercel)
- `backend/` -> FastAPI service (deploy to Render)

Generated runs are persisted to MongoDB (Atlas).

## Structure

```
MolGen/
  backend/
    main.py
    api.py
    requirements.txt
    .env.local
    .env.example
  frontend/
    app/
    package.json
    .env.example
  render.yaml
```

## Local Development

### 1) Install backend deps (from MolGen root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

### 2) Install frontend deps

```powershell
cd frontend
npm install
```

### 3) Backend env file

Create `backend/.env.local` from `backend/.env.example` and set real values.

Minimum required:

```env
MONGODB_ATLAS_URI=mongodb+srv://DB_USER:DB_PASSWORD@cluster0.xxxxx.mongodb.net/molgen?retryWrites=true&w=majority
MONGO_DB_NAME=molgen
MONGO_COLLECTION_NAME=generated_molecules
MONGO_ENABLED=true
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001
```

### 4) Run backend (terminal A)

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 5) Run frontend (terminal B)

```powershell
cd frontend
npm run dev -- --port 3001
```

Open:

- Frontend: http://127.0.0.1:3001
- Backend docs: http://127.0.0.1:8000/docs

## Deploy Frontend on Vercel

Root directory on Vercel:

- `frontend`

Framework:

- Next.js

Required Vercel env variable:

- `NEXT_PUBLIC_API_BASE_URL=https://<your-render-backend>.onrender.com`

Notes:

- In production, frontend requires `NEXT_PUBLIC_API_BASE_URL`.
- If missing, UI will show a clear configuration error.

## Deploy Backend on Render

Use `render.yaml` from project root or create manually.

If creating manually, set:

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Required Render env variables:

- `MONGODB_ATLAS_URI` (real Atlas URI)
- `MONGO_DB_NAME=molgen`
- `MONGO_COLLECTION_NAME=generated_molecules`
- `MONGO_ENABLED=true`

CORS env variables for Vercel:

- `ALLOWED_ORIGINS=https://<your-vercel-domain>.vercel.app`
- Optional for previews: `ALLOWED_ORIGIN_REGEX=https://.*\.vercel\.app`

## End-to-End Deploy Wiring

1. Deploy backend on Render and copy backend URL.
2. Set Vercel `NEXT_PUBLIC_API_BASE_URL` to that Render URL.
3. In Render, allow your Vercel origin through `ALLOWED_ORIGINS` (or regex).
4. Redeploy both services after env changes.

## MongoDB Persistence

Each successful `POST /generate` inserts one document into:

- Database: `molgen`
- Collection: `generated_molecules`

Collection is auto-created on first write.

## Common Errors

### Port in use (EADDRINUSE)

Stop process on the port or choose another port.

### PowerShell path error with Python

Use exact path with no extra spaces:

```powershell
..\.venv\Scripts\python.exe
```

### Atlas connected but no data visible

- Confirm correct Atlas project/cluster
- Confirm IP/network access and DB user permissions
- Trigger at least one successful `/generate` request
- Refresh collection view

## Security

- Never commit real credentials in `.env.local`.
- Rotate MongoDB password if exposed.
- `.env*` files are ignored by git.
