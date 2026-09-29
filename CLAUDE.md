# TRMNL plugins monorepo

- Each plugin lives in `plugins/<name>/` and is a standalone trmnlp project. Create new ones with `bin/new-plugin <name>`, never by hand.
- Run trmnlp commands from the plugin directory via `bin/trmnlp` (uses the gem if installed, else Docker). System Ruby is too old for the gem.
- Verify changes with `bin/trmnlp lint`; preview with `bin/trmnlp serve` (`http://localhost:4567`) or `bin/trmnlp build`.
- `src/settings.yml` is overwritten by `trmnlp pull`. Keep the `id` key once a plugin has been pushed.
- Templates are Liquid + the TRMNL Framework CSS classes (`layout`, `title_bar`, `columns`, `item`, `value`, etc.). Implement all four layouts: full, half_horizontal, half_vertical, quadrant. Put markup shared between layouts in `src/shared.liquid`.
- Target e-ink: grayscale only, no animation or hover, 800x480 full screen. Use framework classes rather than custom CSS.
- Lint counts `padding`, `margin`, `font-size`, `text-align`, `justify-content`, `background-color`, `border-radius`, `object-fit` anywhere in markup (including `<style>`), max 6 total. Use framework classes (`p--`, `m--`, `text--center`, `flex--*`, `rounded`) instead.
- Serverless transforms (`src/transform.py`) have unit tests in `tests/`; run `python3 -m unittest discover tests` from the plugin dir.
- Secrets go in env vars referenced as `{{ env.VAR }}` in `.trmnlp.yml`, never in committed files.
