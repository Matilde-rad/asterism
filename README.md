# ✦ Asterism

Upload a night-sky photo → get every star named, however you held the camera.

## How it works
1. **Read the photo** (`app/photo.py`): EXIF time, GPS and focal length. Canon cameras don't record the
   35 mm-equivalent focal length, so the real sensor width is worked out from the focal-plane resolution.
   That gives the field of view (e.g. Canon 1200D at 18 mm ≈ 64° across).
2. **Match the stars locally with ESA's [tetra3](https://github.com/esa/tetra3)** (`app/solver.py`),
   the algorithm built for spacecraft star trackers:
   - find the stars (bright blobs → pixel positions, brightest first)
   - take 4 stars, measure the 6 distances between them, divide by the longest →
     a fingerprint that doesn't change when you tilt or zoom
   - look it up in a database built from the Hipparcos catalogue
   - verify: predict where other stars should be and check they're there
   Result in milliseconds: where the photo points, how tilted it is, and which star is which.
3. **Name things**: Hipparcos numbers → names (Skyfield's named-star list, MIT) + constellation (astropy).
   If tetra3 can't solve a photo, astrometry.net (`app/nova.py`) is used as a backup.
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

## Build the Canon database (once)
tetra3's built-in database covers photos 10–30° wide. For the Canon 1200D + EF-S 18–55 (23°–64°):
```bash
python scripts/build_database.py
```
It downloads the Hipparcos catalogue (~51 MB) and writes `app/data/canon_1200d_18-55.npz`.
The app picks it up automatically. Commit it so the Docker image includes it.

## Sky simulator
`app/simulate.py` renders a fake camera photo of any part of the sky from the star catalogue.
The tests use it: point a virtual camera at Orion, then check the solver finds Orion again.

## Tests
```bash
pytest -q
```
They run offline: simulated sky photos for tetra3, a fake server for astrometry.net.

## Docker
```bash
docker build -t asterism .
docker run -p 8000:8000 asterism          # add -e ASTROMETRY_API_KEY=... for the backup solver
```

## Ideas for next
- Constellation stick figures (connect named stars)
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
