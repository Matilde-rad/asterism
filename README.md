# ✦ Asterism

Upload a night-sky photo → get every star named, however you held the camera.

## How it works
1. **Read the photo** (`app/photo.py`): EXIF time, GPS and focal length. The focal length gives a rough
   field-of-view hint so the solver searches faster.
2. **Plate solve** (`app/nova.py`): the photo goes to astrometry.net, which picks groups of 4 stars,
   turns each group's *shape* into numbers that don't change with rotation or zoom (the "fingerprint"),
   and looks them up in an index built from star catalogues. Result: exactly where the photo points.
3. **Name things**: astrometry.net returns the named stars/objects with their pixel positions.
4. **Where were you facing?** (`app/sky.py`): with time + location, astropy converts the photo's sky
   position into compass direction and height above the horizon.
5. **Draw it** (`app/static/`): labels drawn on the photo in the browser.

## Run it
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements-dev.txt
set ASTROMETRY_API_KEY=your-key   # Windows  (Linux/Mac: export ASTROMETRY_API_KEY=your-key)
uvicorn app.main:app --reload
```
Open http://localhost:8000

Get a free API key: sign up at https://nova.astrometry.net → your profile → API key.

## Tests
```bash
pytest -q
```
The tests fake the solver, so they run offline.

## Docker
```bash
docker build -t asterism .
docker run -p 8000:8000 -e ASTROMETRY_API_KEY=your-key asterism
```

## Ideas for next
- Constellation stick figures (connect named stars)
- Solve locally (astrometry.net in Docker) instead of the web API
- Planets: compute where they were from time + location and label them
- Job queue (Redis) instead of in-memory jobs, deploy on polaris with Argo CD

## Deploy on polaris (k3s + Argo CD + Cloudflare Tunnel)
1. **Push to GitHub** as `Matilde-rad/asterism`. The workflow runs the tests, then builds and pushes
   `ghcr.io/matilde-rad/asterism:latest`. If the repo is private, make the package public in GitHub
   (Packages → asterism → settings) or add an image pull secret on the cluster.
2. **Create the secret on polaris** (it never goes in git):
   ```bash
   kubectl create namespace asterism
   kubectl -n asterism create secret generic asterism-secrets --from-literal=ASTROMETRY_API_KEY=your-key
   ```
3. **Register the app in Argo CD:** `kubectl apply -f argocd/application.yaml`
4. **Expose it:** add a public hostname to the `polaris` tunnel:
   `asterism.matilde.dev` → `http://asterism.asterism.svc.cluster.local:80`
5. **Updating:** push to main, then `kubectl -n asterism rollout restart deploy/asterism`
   (or later add Argo CD Image Updater to do it automatically).

⚠️ The app uses *your* astrometry.net key. If it's public, anyone can use it.
Put Cloudflare Access in front of it, or keep it tailnet-only like Argo CD, until you add limits.
