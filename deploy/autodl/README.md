# AutoDL production deployment

This deployment uses the AutoDL HTTPS gateway (`:8443` -> container port `6006`),
Nginx Basic Authentication, one Uvicorn worker, and the image's supervised
`/etc/autodl.sh` boot hook. The app and credentials live under
`/root/autodl-tmp/itp-app` and `/root/autodl-tmp/itp-data` respectively.

`configure.py` preserves the configured Tencent, Qwen and SeedDream secrets
from the existing `.env`, sets an exact public HTTPS origin, and points the
Flux Klein and FaceVerse endpoints at the loopback model services on ports
8788 and 8787. It creates the two bearer tokens if they are absent, in root-only
files outside this repository (`itp-flux-klein-service/.token` and
`itp-data/faceverse.token`), and reads them back into `.env`.
It creates a random site password at `itp-data/access-password`; the username
is `itp`. Do not commit the passwords, the tokens, `.env`, or `access.htpasswd`.

The vendor supervisor starts `/etc/autodl.sh` (a copy of `autodl.sh` here), which executes the nested
`supervisord` in this directory. The nested supervisor restarts Uvicorn and
Nginx if they fail. Check status with:

```bash
/root/miniconda3/bin/supervisorctl -c /root/autodl-tmp/itp-app/deploy/autodl/supervisord.conf status
curl -f http://127.0.0.1:8000/api/health
```

Nginx denies public writes to `/api/settings` so website users cannot replace
provider credentials. All other routes require Basic Authentication. The
current app uses one asset database for all authenticated visitors; do not
share the site password with mutually untrusted users. For a public
multi-tenant product, add account isolation, per-user authorization and cost
controls before removing this access gate.

## Model services

`supervisord.conf` also starts the two local model services, last, so the site
answers as soon as the API and Nginx are up:

| Program | Service | Port | Weights |
|---|---|---|---|
| `itp-flux` | FLUX.2 Klein 4B | 8788 | `itp-flux-klein-service/hf-cache`, ~15 GB |
| `itp-faceverse` | FaceVerse V4 | 8787 | `itp-app/services/vendor/FaceVerse_v4/data`, ~276 MB |

Both run through `run-model-service.sh`, which waits for a `/dev/nvidia0`
device node before loading weights. A container booted in AutoDL no-GPU mode
therefore stays in a waiting state instead of crash-looping, and the service
starts by itself once the instance is rebooted with a GPU. Model loading needs
a GPU with enough VRAM for the offload mode in use: `ITP_KLEIN_OFFLOAD=model`
(the default here) peaks near one component and fits a 16 GB card, while
`none` holds all weights on the device and needs a larger allocation. Set
`ITP_KLEIN_MODEL_PATH` to a different snapshot directory after a re-download.

Check the services with:

```bash
/root/miniconda3/bin/supervisorctl -c /root/autodl-tmp/itp-app/deploy/autodl/supervisord.conf status
curl -s http://127.0.0.1:8788/health   # FLUX.2 Klein: ready is true once loaded
curl -s http://127.0.0.1:8787/health   # FaceVerse: reports cuda and the GPU name
```

`ready=false` (Flux) or a startup failure with `CUDA is not available` /
`FileNotFoundError` (FaceVerse) means the container has no GPU or the weights
are missing; the wait loop covers the former, so check `itp-data/*.log`.
