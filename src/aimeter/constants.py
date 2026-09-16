SCORING_MODE = "combined"

API_URL = (
    "https://aistupidlevel.info/dashboard/scores"
    f"?mode=leaderboard&period=7d&sortBy={SCORING_MODE}"
)
HISTORY_URL = (
    "https://aistupidlevel.info/dashboard/history/{model_id}"
    f"?period=7d&sortBy={SCORING_MODE}"
)
REQUEST_TIMEOUT = 10
# Client-side concurrency limit; not an advertised API rate limit.
HISTORY_MAX_WORKERS = 4

# Normal-distribution multiplier for a two-sided 95% confidence interval.
NORMAL_95_CI_MULTIPLIER = 1.96

# Label threshold: max(MIN_THRESHOLD, SE * SE_THRESHOLD_SCALE).
MIN_THRESHOLD = 5.0
SE_THRESHOLD_SCALE = 0.7

# Strong signal [!!] when |Δ| >= STRONG_SIGNAL_MULTIPLIER * threshold.
STRONG_SIGNAL_MULTIPLIER = 2.0

# Above this SE, mark the score with SE↕ as less reliable.
SE_HIGH_THRESHOLD = 10.0

# Built-in default list, used when no user config file exists.
DEFAULT_WATCHED_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "claude-fable-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    # Composer 2.5 is not listed separately; API tracks Kimi K2.x as the base model.
    "kimi-k2.7-code",
]

LABEL_IMPROVED = "improved"
LABEL_WORSENED = "worsened"
LABEL_STABLE = "unchanged"
LABEL_NO_DATA = "no data"
CUMUL_SUM_LABEL = "Cumul. sum"

CUSUM_ARROWS = {"up": "↑", "down": "↓", "stable": "→"}
