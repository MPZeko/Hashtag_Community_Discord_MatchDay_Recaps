# Hashtag United Discord Match Recap Bot

This repository contains a production-ready Python 3.12 bot that checks Football Web Pages public fixture/result pages for Hashtag United Men and Hashtag United Women, detects newly completed matches, and posts one concise Discord embed recap per new result.

## Architecture

The bot is split into small modules under `src/hashtag_bot`:

- `fwp_source.py` is the current Football Web Pages HTML adapter.
- `models.py` contains dataclasses for teams, matches, tables, and goals.
- `recap.py` creates deterministic Discord embed content without inventing events.
- `discord_client.py` posts webhooks with `wait=true` and disabled mentions.
- `state.py` performs atomic duplicate-prevention state writes.
- `cli.py` orchestrates scheduled checks, dry-runs, webhook tests, and manual latest-result posts.

The adapter boundary means a future official LiveScore partner feed or Football Web Pages API can replace `fwp_source.py` while keeping recap, Discord, CLI, and state logic intact. Public HTML pages are used now because no official LiveScore feed credentials are configured. The bot never invents goals, scorers, match events, or table consequences.

## Required GitHub secret

Only one secret is required: `DISCORD_WEBHOOK_URL`.

Add it in GitHub with:

**Settings → Secrets and variables → Actions → New repository secret**

Name the secret `DISCORD_WEBHOOK_URL` and paste the Discord webhook URL as the value.

## GitHub Actions

`Hashtag United Match Recap` runs every ten minutes with cron `3/10 * * * *` on the default branch and can also be started manually with `workflow_dispatch`.

To test the webhook after pushing:

1. Open **Actions**.
2. Select **Hashtag United Match Recap**.
3. Click **Run workflow**.
4. Choose mode `test-webhook` and team `all`.
5. Run it and confirm Discord receives “Hashtag United Match Bot Connected”.

## First initialization

Run mode `check` once from GitHub Actions or locally. If `data/state.json` has `initialized: false`, the bot fetches both teams, records all already completed results as known, saves table snapshots, sets `initialized: true`, and posts nothing. This prevents historical result spam.

## Manual latest-result post

For testing after initialization, run the workflow with mode `post-latest` and team `all`, `men`, or `women`. Locally:

```bash
DISCORD_WEBHOOK_URL='...' python -m hashtag_bot.cli post-latest --team all
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
python -m hashtag_bot.cli dry-run
```

Commands requiring the webhook are:

```bash
python -m hashtag_bot.cli check
python -m hashtag_bot.cli test-webhook
python -m hashtag_bot.cli post-latest --team men
```

`dry-run` fetches and parses live data and prints formatted embed JSON without requiring or using the Discord secret and without changing state.

## State and duplicate prevention

State lives in `data/state.json`. Match keys are deterministic and exclude the score, so a corrected score updates the same match key rather than creating a duplicate. A result is marked posted only after Discord returns success. Atomic writes use a temporary file, flush, fsync, and replace.

## Troubleshooting

- **No fixtures table found**: Football Web Pages may have changed its table headers; update the HTML adapter tests and parser.
- **Website layout changed**: The parser avoids CSS classes, but structural changes may still require adjusting `fwp_source.py`.
- **Webhook returns 401 or 404**: Recreate the Discord webhook and update the `DISCORD_WEBHOOK_URL` repository secret.
- **State push rejected by branch protection**: The workflow commits only `data/state.json`; allow the GitHub Actions bot to push or relax protection for that file.
- **GitHub Actions schedule delayed**: GitHub scheduled workflows can run late during platform load; use manual `workflow_dispatch` if timing is critical.
