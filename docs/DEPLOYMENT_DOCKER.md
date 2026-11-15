# Docker deployment with Caddy

ENOM runs as three containers from the default `compose.yaml`: FastAPI (`api`),
the built React app served by Nginx (`web`), and Caddy (`caddy`) for HTTPS. Only
Caddy publishes ports 80 and 443. Nginx sends `/api/` requests to FastAPI over
the private Compose network.

## What persists on the production host

The images deliberately omit generated data and downloaded tiles. Compose
bind-mounts the existing production `data/`, `artifacts/`, and offline tile
directories into the API container. This keeps local raster/model assets out of
Docker build contexts and preserves the host's current data. Offline tiles are
downloaded by ENOM itself from **Save maps offline** after the app is running.

The API container runs as UID/GID 1000, matching the current `jamels` account on
`enom`, so downloaded tiles and offline-map state remain writable in those
host directories.

## First-time host setup

The current `enom` host has no Docker or Caddy service installed. Install Docker
Engine and its Compose plugin on that host, then ensure the domain's DNS A
record points to its public IP and that inbound TCP ports 80 and 443 (plus UDP
443 for HTTP/3) are allowed. Caddy runs in Compose and obtains/manages the TLS
certificate automatically.

Build the frontend on your development machine first. This avoids running the
memory-heavy TypeScript/Vite compile on the production host. Vite copies only
the three base globe textures into `dist`; the gigabyte-scale offline tile
cache is not part of the web build:

```sh
cd apps/twinworld
npm ci
npm run build
cd ../..
scripts/sync-to-enom-prod.sh
```

Then on the host:

```sh
cd /home/jamels/ENOM
mkdir -p data artifacts apps/twinworld/public/tiles/offline
sudo docker compose up -d --build
```

The default `compose.yaml` uses `enom.earth` for Caddy. Its DNS A/AAAA records
must point to this server, and ports 80 and 443 must be reachable, for Caddy to
obtain a trusted TLS certificate.

Useful operations:

```sh
sudo docker compose ps
sudo docker compose logs -f api web caddy
sudo docker compose pull caddy
sudo docker compose up -d --build
```

The offline map download is started in the app's **Save maps offline** dialog.
The downloaded files stay under `apps/twinworld/public/tiles/offline/` on the
host and are excluded from both frontend builds and later syncs.

## Access control

TLS encrypts traffic but does not authenticate visitors. The current API has
write actions for starting, cancelling, and clearing the offline tile package,
and those routes do not require a login. Before exposing ENOM to the public
internet, add an access-control layer (for example, Caddy Basic Auth or an
identity-aware proxy) or restrict access at the network layer.

## Limits

Docker build and container health do not validate the scientific data or
guarantee the visual-retrieval artifacts are present. The API needs the
production host's existing data and artifacts mounts; absent rasters or model
embeddings remain unavailable just as they do in a local checkout.
