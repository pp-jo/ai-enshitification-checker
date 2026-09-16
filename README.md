# aimeter

[English](#english) | [Polski](#polski)

## English

A CLI for checking AI model trends using the public [AI Stupid Meter](https://aistupidlevel.info/) API.

It compares the current score with the 7-day average and prints a short summary in the terminal.

A vibe-coded prototype.

### Installation

```bash
uv tool install /path/to/this/repo
```

Or locally:

```bash
uv sync --dev
```

### Usage

```bash
aimeter
```

Or from the repository:

```bash
uv run aimeter
```

Supports up to 2 verbosity levels (anything beyond `-vv` is treated as `-vv`).

To update, run:

```bash
uv tool upgrade aimeter
```

### Local development checks

```bash
uv sync --locked --dev
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/aimeter
```

Ruff checks source and tests for common coding mistakes and import order, and
formats them with an 88-character line-length target. To apply safe lint fixes and
formatting locally:

```bash
uv run --locked ruff check --fix .
uv run --locked ruff format .
```

Mypy checks `src/aimeter` for Python 3.11 compatibility with `strict = false`.
It checks function bodies even without annotations, reports incompatible types
and unsafe use of `None`, and warns about returning `Any` from typed functions or
unused `type: ignore` comments. Full annotations are not required; tests are not
included in the Mypy check. These checks complement runtime validation and tests
for invalid API data, NaN, and infinity.

### Output and diagnostics

The report goes to stdout. API errors and warnings go to stderr, including history
failures (HTTP status, timeout, network errors, invalid JSON or data), discarded
history point counts, invalid leaderboard fields, and numeric calculation errors.
Warnings include the model and field where available and appear once, even without `-v`.

With `-v` or `-vv`, stderr also includes `[INFO]` explanations for a missing current
score, an empty history, or a missing history identifier. A valid empty history is
not a request failure. Available scores and history statistics remain in the report.
Models absent from the leaderboard keep their existing warning in the stdout report.

Exit codes: **0** means the run succeeded, including partial results, an empty
leaderboard, or an empty watch list; **1** means the leaderboard could not be read or validated;
**2** means invalid arguments or configuration. Code 0 does not guarantee complete data.
With a nonempty watch list, an empty leaderboard produces a warning on stderr and no report.

To capture the streams separately:

```bash
aimeter -v >report.txt 2>diagnostics.txt
```

### Fetching histories

After reading the leaderboard once, aimeter fetches the selected histories with
up to 4 concurrent HTTP requests, at most once per run per history ID. A failed history still produces a partial result and a warning, including HTTP 429; requests are not retried automatically.

When stderr is a terminal, `[INFO] Fetching model histories…` appears before
fetching histories. Redirecting stderr suppresses this progress message. The report
is printed after all histories finish. An empty `watched_models = []` produces a
zero-model summary without any HTTP requests.

There is no cache between runs and no additional runtime dependency.

### Configuration

You can save a custom list of watched models in a TOML file without editing the code.
The program selects its configuration in the following order:

1. The file specified by the `--config /path/to/config.toml` flag.
2. The user configuration file: `$XDG_CONFIG_HOME/aimeter/config.toml`, or
   `~/.config/aimeter/config.toml` if the variable is unset, empty, or contains a relative path.
3. The built-in default list if `--config` is not provided and the user configuration file does not exist.

#### Configuration file

Create an `aimeter` directory in your chosen configuration location, then create a
`config.toml` file inside it, for example:

```toml
watched_models = [
    "gpt-5.6-sol",
    "gpt-5.5",
    "claude-sonnet-4-6",
    "kimi-k2.7-code",
]
```

**The list in the file replaces the entire default list**, preserving the specified order.
The `watched_models` field is required and must be a list of non-empty model names recognized
by the API. An empty list, `watched_models = []`, means no models are watched.

Once you save the file in the user configuration location, you can run `aimeter`
from any directory.

#### Linux, macOS, and Windows

Default location when `XDG_CONFIG_HOME` is not set:

| System | Example path |
|---|---|
| Linux | `/home/username/.config/aimeter/config.toml` |
| macOS | `/Users/username/.config/aimeter/config.toml` |
| Windows, including Git Bash | `C:/Users/username/.config/aimeter/config.toml` |

On Windows, Python determines the home directory using `USERPROFILE`
(or `HOMEDRIVE` and `HOMEPATH`). If you change `HOME` in Git Bash, Bash's `~` may
point to a different location. When setting a custom `XDG_CONFIG_HOME` on Windows,
use an absolute Windows path, such as `C:/Users/username/.config`.

### How the assessment works

Everything uses **COMBINED** mode — the same mode shown by default in the website's chart.

The script fetches the following from the leaderboard (`sortBy=combined`):

- `currentScore` — the current COMBINED score
- `trend` — the CUSUM direction (the short-term trend over the last ~48 hours)

We calculate the **7-day average and 7-day maximum** ourselves from the chart history:
`dashboard/history/{id}?period=7d&sortBy=combined` — the arithmetic mean and highest value of the `score` points
from the last 7 days (~42 measurements taken every 4 hours). We do not use `periodAvg` from the leaderboard API
because it mixes COMBINED with TOOLING and REASONING, lowering the baseline relative to the chart.

A higher score means better performance — the benchmarks measure coding ability.

**Delta** is the difference: `current score − 7-day COMBINED average`. A positive delta means the model is performing better now than over the past week.

The **threshold** is calculated dynamically from the measurement error (SE, or standard error, calculated from the same COMBINED points):
`threshold = max(5, SE × 0.7)`. Models with widely varying scores (high SE) get a higher threshold
so that small fluctuations do not trigger false alarms. The minimum threshold is 5.

The **label** is assigned by comparing delta with the threshold:

- `improved` — delta ≥ +threshold
- `worsened` — delta ≤ −threshold
- `unchanged` — delta falls within (−threshold, +threshold); a drop may be visible in Δ, but it does not exceed measurement noise
- `no data` — the current score or usable 7-day COMBINED history is unavailable, or the calculation exceeds the numeric range; the row keeps the available values, but shows no Δ or assessment

Scores must be finite numbers. Booleans and numeric strings are treated as missing
values. Invalid history points are discarded; all period statistics use the same
remaining points. An empty history or one without valid points provides no baseline.

An absent or invalid `trend` is shown as `Cumul. sum:?` (unknown), while an explicit
`stable` is shown as `→`. An unknown trend does not prevent a strong signal from
a sufficiently large drop. Invalid optional metadata is omitted.

**`-vv`** shows two types of numbers on one line:

- **COMBINED 7d** (points, CI) — calculated locally from the chart history, using the same dataset as Δ and SE
- **stability (API)** — the leaderboard's `stability` field; the server calculates it using its own method, whose exact inputs we do not know, so it provides just additional context and is not part of our assessment

The **strong signal `[!!]`** appears only with `worsened` and when at least one condition is met:
the drop is large relative to the threshold (|Δ| ≥ 2 × threshold), or CUSUM also indicates deterioration.
Without `[!!]`, the `worsened` label is a weaker signal — it may reflect noise or a temporary dip.
Near a threshold, comparisons show one decimal place; if that still hides the difference, `≈` marks approximate values and the explanation states whether the value is below or above the threshold before rounding.
The Δ calculation line also uses `≈` when any displayed value is rounded.

**CUSUM** (Cumulative Sum) is an independent API algorithm that looks at a ~48-hour window. It answers
"is the model changing *now*?", rather than "is it worse than a week ago?". It is shown as context,
not as the main label. A disagreement between CUSUM and the label (for example, `worsened` + `CUSUM:↑`)
means the model declined over the week but recovered slightly in the last 48 hours.

**`SE↕`** appears when the measurement error exceeds 10 — the score is then unreliable and may
vary significantly between benchmark runs.
