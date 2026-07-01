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

# Próg decyzyjny dla etykiety: max(MIN_THRESHOLD, SE * SE_THRESHOLD_SCALE).
MIN_THRESHOLD = 5.0
SE_THRESHOLD_SCALE = 0.7

# Silny sygnał [!!] przy |Δ| >= STRONG_SIGNAL_MULTIPLIER * próg.
STRONG_SIGNAL_MULTIPLIER = 2.0

# Powyżej tej wartości SE oznaczamy wynik markerem SE↕ jako mało wiarygodny.
SE_HIGH_THRESHOLD = 10.0

WATCHED_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    # Composer 2.5 is not listed separately; API tracks Kimi K2.x as the base model.
    "kimi-k2.7-code",
]

LABEL_IMPROVED = "poprawił się"
LABEL_WORSENED = "pogorszył się"
LABEL_STABLE = "bez zmian"
LABEL_NO_DATA = "brak danych"

CUSUM_ARROWS = {"up": "↑", "down": "↓", "stable": "→"}
