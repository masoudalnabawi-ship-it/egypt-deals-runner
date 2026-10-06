#!/usr/bin/env bash
set -euo pipefail

say(){ printf '\n==> %s\n' "$*"; }
fail(){ printf '\n❌ %s\n' "$*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] || fail "Run this from inside egypt-deals-runner-v2-deploy"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != "v14-cloudflare" ]; then
  if git show-ref --verify --quiet refs/heads/v14-cloudflare; then
    git checkout v14-cloudflare
  else
    git checkout -b v14-cloudflare v14-smart-engine
  fi
fi

[ -d cloudflare_v14 ] || fail "cloudflare_v14 folder is missing. Extract the supplied bundle into the repo root first."
cd cloudflare_v14

say "Installing Cloudflare build tools"
npm install --no-audit --no-fund --loglevel=notice

say "Ensuring Cloudflare queue exists"
if ! npx wrangler queues create egypt-deals-v14-jobs >/tmp/v14_queue_create.log 2>&1; then
  if ! grep -Eqi 'already|exists' /tmp/v14_queue_create.log; then
    cat /tmp/v14_queue_create.log
    fail "Could not create the queue"
  fi
fi
if ! grep -Eqi 'already|exists|taken' /tmp/v14_queue_create.log; then
  cat /tmp/v14_queue_create.log || true
else
  echo "  ✓ Queue already exists"
fi

say "Applying D1 migrations"
npx wrangler d1 migrations apply egypt-deals-v14-db --remote

say "Importing Telegram settings securely (single-bot mode)"
python3 - <<'PY'
from __future__ import annotations

import getpass
import os
import secrets
import subprocess
from pathlib import Path

cf = Path.cwd()
repo = cf.parent

def load_env():
    out = {}

    for base in (repo, cf):
        for p in base.glob(".env*"):
            if not p.is_file():
                continue

            try:
                lines = p.read_text(
                    encoding="utf-8",
                    errors="ignore"
                ).splitlines()
            except Exception:
                continue

            for raw in lines:
                line = raw.strip()

                if (
                    not line
                    or line.startswith("#")
                    or "=" not in line
                ):
                    continue

                if line.startswith("export "):
                    line = line[7:].strip()

                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()

                if (
                    len(v) >= 2
                    and v[0] == v[-1]
                    and v[0] in "'\\\""
                ):
                    v = v[1:-1]

                out.setdefault(k, v)

    return out

vals = load_env()

def value(name):
    return (
        os.environ.get(name)
        or vals.get(name)
        or ""
    ).strip()

def first(*names):
    for name in names:
        v = value(name)

        if v:
            return v

    return ""

def put(name, value):
    cp = subprocess.run(
        [
            "npx",
            "wrangler",
            "secret",
            "put",
            name,
        ],
        input=value + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if cp.returncode != 0:
        print(cp.stdout)
        raise SystemExit(
            f"Failed to set {name}"
        )

    print(f"  ✓ {name}")

required = {
    "TELEGRAM_BOT_TOKEN":
        first("TELEGRAM_BOT_TOKEN"),

    "AMAZON_NORMAL_REVIEW_CHAT_ID":
        first(
            "V13_NORMAL_REVIEW_CHAT_ID",
            "REVIEW_CHAT_ID",
            "AMAZON_NORMAL_REVIEW_CHAT_ID",
        ),

    "AMAZON_REVIEW_GROUP_ID":
        first(
            "V13_ULTRA_REVIEW_CHAT_ID",
            "AMAZON_REVIEW_GROUP_ID",
        ),
}

for name, val in list(required.items()):
    if not val:
        val = getpass.getpass(
            f"{name} (hidden input): "
        ).strip()

        if not val:
            raise SystemExit(
                f"Missing required value: {name}"
            )

        required[name] = val

for name, val in required.items():
    put(name, val)

# Noon intentionally uses the main Telegram bot.
# Noon routing remains NORMAL ONLY inside V14 policy.

for name in (
    "AMAZON_CHANNEL_ID",
    "NOON_CHANNEL_ID",
    "TELEGRAM_CHANNEL_ID",
):
    val = value(name)

    if val:
        put(name, val)

admin = (
    value("V14_ADMIN_KEY")
    or secrets.token_urlsafe(32)
)

webhook_secret = (
    value("TELEGRAM_WEBHOOK_SECRET")
    or secrets.token_urlsafe(32)
)

put("V14_ADMIN_KEY", admin)
put(
    "TELEGRAM_WEBHOOK_SECRET",
    webhook_secret
)

state = repo / ".runtime_state"
state.mkdir(exist_ok=True)

keyfile = (
    state
    / "v14-cloudflare-admin-key"
)

keyfile.write_text(
    admin,
    encoding="utf-8"
)

os.chmod(
    keyfile,
    0o600
)

print("✅ SINGLE_BOT_TELEGRAM_READY")
PY

say "Typechecking + V14 policy self-test + Wrangler dry run"
npm run check

say "Deploying V14 Cloudflare Worker"
DEPLOY_OUT="$(mktemp)"
npx wrangler deploy | tee "$DEPLOY_OUT"
URL="$(grep -Eo 'https://[^[:space:]]+\.workers\.dev' "$DEPLOY_OUT" | tail -1 || true)"
rm -f "$DEPLOY_OUT"
[ -n "$URL" ] || fail "Deployment finished but the workers.dev URL could not be detected"

ADMIN_KEY="$(cat ../.runtime_state/v14-cloudflare-admin-key)"
say "Registering both Telegram webhooks"
curl -fsS -X POST "$URL/admin/bootstrap?key=$ADMIN_KEY" | tee /tmp/v14_bootstrap.json
printf '\n'

grep -q '"ok":true' /tmp/v14_bootstrap.json || fail "Telegram webhook bootstrap failed"

say "Running one controlled production cycle"
curl -fsS -X POST "$URL/admin/run?key=$ADMIN_KEY" | tee /tmp/v14_cycle.json
printf '\n'

say "Health check"
curl -fsS "$URL/health" | tee /tmp/v14_health.json
printf '\n'
grep -q '"ok":true' /tmp/v14_health.json || fail "Health check failed"

cd "$ROOT"
say "Saving Cloudflare V14 branch to GitHub"
git add cloudflare_v14
git diff --cached --check
if ! git diff --cached --quiet; then
  git commit -m "Cloudflare V14 production worker with D1, Queue and Browser Run"
fi
git push -u origin v14-cloudflare

printf '\n✅ V14_CLOUDFLARE_DEPLOY_OK\nWORKER_URL=%s\n' "$URL"
printf 'Health: '; cat /tmp/v14_health.json; printf '\n'
