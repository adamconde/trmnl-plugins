# TRMNL Plugins

Private plugins for [TRMNL](https://trmnl.com) e-ink displays. Each plugin in `plugins/` is a standalone [trmnlp](https://github.com/usetrmnl/trmnlp) project.

## Requirements

One of:

- [Docker](https://docs.docker.com/get-docker/) (no local Ruby needed), or
- Ruby 3.4+ and `gem install trmnl_preview`

The scripts use the local `trmnlp` gem if present, otherwise the `trmnl/trmnlp` Docker image.

## Layout

```text
bin/new-plugin              scaffold a new plugin
plugins/<name>/
  .trmnlp.yml               local preview config (custom field values, variable overrides)
  bin/trmnlp                trmnlp wrapper (gem or Docker)
  src/settings.yml          plugin settings uploaded to TRMNL (strategy, polling URL, fields, id)
  src/full.liquid           full-screen layout
  src/half_horizontal.liquid
  src/half_vertical.liquid
  src/quadrant.liquid
  src/shared.liquid         markup shared by all layouts
  src/transform.py.example  optional serverless transform (rename to enable)
.github/workflows/trmnl.yml lint every plugin on PR; push to TRMNL on main
```

## Workflow

```bash
# create a plugin
bin/new-plugin weather

# preview locally with live reload at http://localhost:4567
cd plugins/weather
bin/trmnlp serve

# validate
bin/trmnlp lint

# publish (first push creates the plugin and writes its `id` to src/settings.yml; commit it)
bin/trmnlp login
bin/trmnlp push

# pull settings changed in the TRMNL web UI
bin/trmnlp pull

```

To import an existing private plugin, run `trmnlp clone <name> <id>` from `plugins/` (with Docker: `docker run --rm -it -v "$HOME/.config/trmnlp:/root/.config/trmnlp" -v "$(pwd):/plugin" trmnl/trmnlp clone <name> <id>`), then delete any `.git`/`.github` it creates.

`trmnlp login` stores your API key in `~/.config/trmnlp`, which the Docker wrapper mounts.

## Secrets

Don't commit API keys or tokens. Reference environment variables in `.trmnlp.yml` with `{{ env.VAR_NAME }}`, and keep local values in `.env` files (gitignored).

## CI/CD

`.github/workflows/trmnl.yml` runs `trmnlp lint` for every plugin on pull requests. On `main`, it runs `trmnlp push --force` for each plugin whose `src/settings.yml` has an `id`. Plugins without an `id` are skipped so CI doesn't create duplicates. Add a `TRMNL_API_KEY` repository secret to enable pushes.

## References

- [trmnlp](https://github.com/usetrmnl/trmnlp)
- [TRMNL Framework (design system)](https://trmnl.com/framework)
- [Private plugin import/export format](https://help.trmnl.com/en/articles/10542599-importing-and-exporting-private-plugins)
