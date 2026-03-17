# Expose backend with Cloudflare Tunnel (for Vercel)

Use a **Cloudflare Named Tunnel** so your local backend gets a **stable public URL** that works from any computer when users open your Vercel app. Quick Tunnels (`trycloudflare.com`) change on restart and can show an "access" page; a named tunnel avoids that.

---

## Step 1: Install cloudflared (Windows)

1. Download the Windows installer:  
   https://github.com/cloudflare/cloudflared/releases/latest  
   Get `cloudflared-windows-amd64.exe` (or `cloudflared-windows-386.exe` for 32-bit).

2. Rename it to `cloudflared.exe` and either:
   - Put it in a folder (e.g. `C:\cloudflared`) and add that folder to your **PATH**, or  
   - Move it to a folder that’s already on PATH (e.g. `C:\Windows` or your user folder).

3. Open **PowerShell** and check:
   ```powershell
   cloudflared --version
   ```

---

## Step 2: Sign in to Cloudflare (free account)

1. Run:
   ```powershell
   cloudflared tunnel login
   ```
2. A browser window opens. Log in or sign up at Cloudflare.
3. Pick the domain you want to use for the tunnel (you can use Cloudflare’s free subdomain `*.cfargotunnel.com`; no custom domain required).
4. When it says “You have successfully logged in”, close the browser and go back to PowerShell.

---

## Step 3: Create a named tunnel (stable URL)

1. Create a tunnel and note the tunnel ID it prints:
   ```powershell
   cloudflared tunnel create molgen-backend
   ```
   You’ll see something like: `Created tunnel molgen-backend with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.

2. List tunnels to confirm:
   ```powershell
   cloudflared tunnel list
   ```

---

## Step 4: Create a config file for the tunnel

1. Create a folder for config (if you don’t have one), e.g.:
   ```powershell
   New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.cloudflared"
   ```

2. Create the config file  
   `%USERPROFILE%\.cloudflared\config.yml`  
   (e.g. `C:\Users\HP\.cloudflared\config.yml`) with this content (replace `YOUR_TUNNEL_ID` with the id from Step 3):

   ```yaml
   tunnel: YOUR_TUNNEL_ID
   credentials-file: C:\Users\HP\.cloudflared\YOUR_TUNNEL_ID.json

   ingress:
     - hostname: molgen-backend.your-cfargotunnel-subdomain.cfargotunnel.com
       service: http://127.0.0.1:8000
     - service: http_status:404
   ```

   You need a **real hostname**. Get it from the dashboard:

   - Go to https://one.dash.cloudflare.com/ (Zero Trust).
   - **Networks** → **Tunnels** → click **molgen-backend**.
   - Under **Public Hostname**, click **Add a public hostname**:
     - **Subdomain**: e.g. `molgen-backend` (or leave blank to get a random one).
     - **Domain**: choose the one ending in `cfargotunnel.com` (e.g. `xxxxx.cfargotunnel.com`).
     - **Service type**: HTTP.
     - **URL**: `localhost:8000`.
   - Save. The full hostname will be like `molgen-backend.xxxxx.cfargotunnel.com`.

3. The credentials file from Step 3 is at `%USERPROFILE%\.cloudflared\<TUNNEL_ID>.json`. Use that same `<TUNNEL_ID>` in `tunnel:` and `credentials-file:` above. Use the **exact** hostname from the dashboard in `hostname:` (no `https://`).

---

## Step 5: Run the backend and the tunnel

1. Start your backend (in one terminal):
   ```powershell
   cd C:\Users\HP\Desktop\electrothon\electrothon-molgen\backend
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

2. In **another** terminal, start the tunnel:
   ```powershell
   cloudflared tunnel run molgen-backend
   ```
   Leave both running. Your backend is now available at  
   `https://molgen-backend.xxxxx.cfargotunnel.com`  
   (or whatever hostname you set).

3. Test in a browser (from any computer):
   ```text
   https://molgen-backend.xxxxx.cfargotunnel.com/
   ```
   You should see the backend JSON (e.g. `{"status":"ok",...}`). No “access only on this computer” page.

---

## Step 6: Allow your Vercel app in the backend (CORS)

So the frontend on Vercel (opened from **any** computer) can call the backend:

1. Open your backend `.env` or `.env.local` in the `backend` folder (create from `.env.example` if needed).

2. Set **ALLOWED_ORIGINS** to include your **exact** Vercel URL (and keep localhost for local dev):
   ```env
   ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://YOUR_APP.vercel.app
   ```
   Replace `YOUR_APP.vercel.app` with your real Vercel URL (e.g. `electrothon-molgen.vercel.app`).

3. Optional: the project already has:
   ```env
   ALLOWED_ORIGIN_REGEX=https://.*\.vercel\.app
   ```
   That allows **all** `*.vercel.app` domains (production and previews). If you keep this, CORS will work from any Vercel deployment; you can still set `ALLOWED_ORIGINS` as above for clarity.

4. Restart the backend so it picks up the new env.

---

## Step 7: Set the backend URL in Vercel

1. Open your project on **Vercel** → **Settings** → **Environment Variables**.

2. Add:
   - **Name**: `NEXT_PUBLIC_API_BASE_URL`
   - **Value**: `https://molgen-backend.xxxxx.cfargotunnel.com`  
     (no trailing slash; use your real tunnel hostname from Step 4.)

3. Add it for **Production** (and optionally Preview/Development if you use them).

4. **Redeploy** the app (Deployments → ⋮ on latest → Redeploy) so the new variable is applied.

---

## Step 8: Use the Vercel link on any computer

- Open your app at `https://YOUR_APP.vercel.app` from **any** device or network.
- The frontend will call `NEXT_PUBLIC_API_BASE_URL` (your tunnel URL). Because:
  - The tunnel URL is **stable** and **public** (no “only this computer” page),
  - CORS is set to allow your Vercel origin (and optionally all `*.vercel.app`),
  - it will work without extra “access” prompts.

**Important:** The **backend** and **cloudflared tunnel** must be **running** on your machine whenever you want the deployed Vercel app to reach the backend. If you close the backend or the tunnel, the Vercel site will get connection errors until you start them again.

---

## Quick reference

| What | Where |
|------|--------|
| Backend URL (for Vercel) | `https://<your-tunnel-hostname>` (e.g. `https://molgen-backend.xxxxx.cfargotunnel.com`) |
| Vercel env var | `NEXT_PUBLIC_API_BASE_URL` = that URL |
| Backend CORS | `ALLOWED_ORIGINS` includes `https://YOUR_APP.vercel.app`; optional `ALLOWED_ORIGIN_REGEX=https://.*\.vercel\.app` |
| Run backend | `uvicorn main:app --reload --host 127.0.0.1 --port 8000` |
| Run tunnel | `cloudflared tunnel run molgen-backend` |

---

## Troubleshooting

- **“Access” or “only this computer” page**  
  You’re likely using a **Quick Tunnel** (`trycloudflare.com`). Use a **named tunnel** (Steps 2–4) and the hostname from the Zero Trust dashboard.

- **CORS errors from Vercel**  
  Ensure `ALLOWED_ORIGINS` or `ALLOWED_ORIGIN_REGEX` in the backend includes your Vercel URL (and that you restarted the backend after changing `.env`).

- **502 / connection refused**  
  Backend or tunnel not running; start both (Step 5) and check that the tunnel config points to `http://127.0.0.1:8000`.
