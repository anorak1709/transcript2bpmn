# Public demo on Render (free, no card)

The same demo as `docs/deploy-fly.md`, on free tiers that don't ask for a card: Render runs the app;
Neon, Upstash and Supabase provide Postgres, Redis and file storage. AI is switched off (`DEMO_MODE`).

Limits of the free plan:
- The app sleeps after 15 minutes without visitors. The next visit takes about a minute to wake it.
- 512 MB of memory and a tenth of a CPU. All exports fit, with a peak of about 385 MB measured, but PNG and PDF are slow.

## 1. Postgres: Neon
1. Sign up at https://neon.tech and create a project. Pick the region closest to Render's (Singapore → `aws-ap-southeast-1`).
2. Under **Connect**, copy the connection string (`postgresql://…?sslmode=require`). This is `DATABASE_URL`.

## 2. Redis: Upstash
1. Sign up at https://upstash.com and create a Redis database (free; region near Singapore).
2. Copy the TLS URL, the one that starts with `rediss://default:…@….upstash.io:6379`. This is `REDIS_URL`.

## 3. File storage: Supabase
1. Sign up at https://supabase.com and create a project (any name; note its region).
2. **Storage → New bucket**, name `transcripts`, private. This is `S3_BUCKET`.
3. **Project Settings → Storage → S3 Connection**: copy the endpoint (`S3_ENDPOINT_URL`) and region (`S3_REGION`).
4. Under **S3 Access Keys**, choose **New access key**. Copy the key ID (`S3_ACCESS_KEY`) and the secret (`S3_SECRET_KEY`).

## 4. The app: Render
1. Sign up at https://render.com with GitHub and give it access to the `transcript2bpmn` repository.
2. Choose **New → Blueprint**, pick the repository, and Render reads `render.yaml`.
3. Paste the seven values from steps 1–3 when asked, then choose **Apply**.
4. The first build takes about 10 minutes. Then open `https://transcript2bpmn-demo.onrender.com/app/` and click **Try the demo**.

Every push to `master` redeploys. Logs are in the service's **Logs** tab.

## Notes
- Migrations run on each start (`scripts/start-render.sh`). The hourly cleanup of expired demo workspaces runs inside the web process
  (`IN_PROCESS_CRONS`), because a worker isn't free on Render.
- "Try the demo" is limited to 3 a minute per IP and 20 a minute overall. The overall limit still holds if someone
  fakes their IP behind Render's proxy.
- Sign-in links go to the Logs tab unless you set `RESEND_API_KEY` and `EMAIL_FROM` (see `docs/deploy-fly.md`).
