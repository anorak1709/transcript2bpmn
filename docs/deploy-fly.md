# Public demo on Fly.io

The demo runs the real app with AI switched off (`DEMO_MODE=true`) and one-click sandbox
workspaces (`DEMO_SANDBOXES=true`): a visitor clicks **Try the demo** and gets their own fresh
copy of the sample processes, deleted after 24 hours by the worker's hourly cleanup. Nothing
on this deployment can call an AI provider, so it costs only hosting.

You need a Fly.io account and `flyctl` (`brew install flyctl`, then `fly auth login`).

## One-time setup

```bash
# 1. The app (edit `app = ...` in fly.toml first if the name is taken)
fly launch --no-deploy --copy-config

# 2. Postgres: attaching sets DATABASE_URL (postgres://… is accepted as-is)
fly postgres create --name transcript2bpmn-demo-db --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1
fly postgres attach transcript2bpmn-demo-db

# 3. Redis (Upstash, via Fly): copy the redis:// URL it prints
fly redis create --name transcript2bpmn-demo-redis --no-replicas
fly secrets set REDIS_URL='redis://default:…@fly-transcript2bpmn-demo-redis.upstash.io:6379'

# 4. Object storage (Tigris, S3-compatible): it prints credentials; map them to our names
fly storage create --name transcript2bpmn-demo-files
fly secrets set S3_ENDPOINT_URL=https://fly.storage.tigris.dev \
  S3_ACCESS_KEY=<AWS_ACCESS_KEY_ID> S3_SECRET_KEY=<AWS_SECRET_ACCESS_KEY> S3_BUCKET=<BUCKET_NAME>

# 5. The app's public address (used in sign-in emails)
fly secrets set PUBLIC_URL=https://transcript2bpmn-demo.fly.dev

# 6. Optional, for real sign-ups by email (Resend, verified sending domain)
fly secrets set RESEND_API_KEY=re_… EMAIL_FROM='Transcript to BPMN <login@yourdomain.com>'
```

## Deploy

```bash
fly deploy
fly scale count app=1 worker=1
open https://transcript2bpmn-demo.fly.dev/app/   # → "Try the demo"
```

`fly deploy` builds the same Docker image as local, runs migrations once (`release_command`),
then starts the web and worker machines. Logs: `fly logs`.

## Notes

- Without `RESEND_API_KEY`, magic links are written to `fly logs` instead of emailed: fine for a
  demo, not for real users.
- To turn the demo into a real deployment later: remove `DEMO_MODE`/`DEMO_SANDBOXES`, set the
  `LLM_*` / `MODEL_*` secrets (see the README), and redeploy.
- The bucket must exist before the first upload; Tigris creates it with `fly storage create`.
