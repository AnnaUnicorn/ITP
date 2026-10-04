# AutoDL production deployment

This deployment uses the AutoDL HTTPS gateway (`:8443` -> container port `6006`),
Nginx Basic Authentication, one Uvicorn worker, and the image's supervised
`/etc/autodl.sh` boot hook. The app and credentials live under
`/root/autodl-tmp/itp-app` and `/root/autodl-tmp/itp-data` respectively.

`configure.py` preserves the configured Tencent, Qwen and SeedDream secrets
from the existing `.env`, sets an exact public HTTPS origin, and disables the
Flux Klein and FaceVerse endpoints while their model services are inactive.
It creates a random site password at `itp-data/access-password`; the username
is `itp`. Do not commit either this password, `.env`, or `access.htpasswd`.

The vendor supervisor starts `/etc/autodl.sh`, which executes the nested
`supervisord` in this directory. The nested supervisor restarts Uvicorn and
Nginx if they fail. Check status with:

```bash
supervisorctl -c /root/autodl-tmp/itp-app/deploy/autodl/supervisord.conf status
curl -f http://127.0.0.1:8000/api/health
```

Nginx denies public writes to `/api/settings` so website users cannot replace
provider credentials. All other routes require Basic Authentication. The
current app uses one asset database for all authenticated visitors; do not
share the site password with mutually untrusted users. For a public
multi-tenant product, add account isolation, per-user authorization and cost
controls before removing this access gate.

No Flux or FaceVerse model process is started here. Their source and import
chains can be checked independently without allocating GPU or making a model
request; actual inference readiness is not established by those checks.
