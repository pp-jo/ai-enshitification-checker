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

### Tests

```bash
uv run pytest
```

### Output and diagnostics

The report goes to stdout. API errors and warnings go to stderr, including history
failures (HTTP status, timeout, network errors, invalid JSON or data), discarded
history point counts, invalid leaderboard fields, and numeric calculation errors.
Warnings include the model and field where available and appear once, even without `-v`.

With `-v` or `-vv`, stderr also includes `[INFO]` explanations for a missing current
score, an empty history, or a missing history identifier. A valid empty history is
not a request failure. Available scores and history statistics remain in the report.
Models absent from the leaderboard keep their existing warning in the stdout report.

Exit codes: **0** means the leaderboard was read, including partial results or an
empty model list; **1** means the leaderboard could not be read or validated;
**2** means invalid arguments or configuration. Code 0 does not guarantee complete data.
An empty leaderboard produces a warning on stderr and no report.

To capture the streams separately:

```bash
aimeter -v >report.txt 2>diagnostics.txt
```

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

The **label** is assigned by comparing delta with the threshold (the CLI labels are in Polish):

- `poprawił się` (improved) — delta ≥ +threshold
- `pogorszył się` (worsened) — delta ≤ −threshold
- `bez zmian` (unchanged) — delta falls within (−threshold, +threshold); a drop may be visible in Δ, but it does not exceed measurement noise
- `brak danych` (no data) — the current score or usable 7-day COMBINED history is unavailable, or the calculation exceeds the numeric range; the row keeps the available values, but shows no Δ or assessment

Scores must be finite numbers. Booleans and numeric strings are treated as missing
values. Invalid history points are discarded; all period statistics use the same
remaining points. An empty history or one without valid points provides no baseline.

An absent or invalid `trend` is shown as `Cumul. sum:?` (unknown), while an explicit
`stable` is shown as `→`. An unknown trend does not prevent a strong signal from
a sufficiently large drop. Invalid optional metadata is omitted.

**`-vv`** shows two types of numbers on one line:

- **COMBINED 7d** (points, CI) — calculated locally from the chart history, using the same dataset as Δ and SE
- **stabilność (API)** (stability) — the leaderboard's `stability` field; the server calculates it using its own method, whose exact inputs we do not know, so it provides just additional context and is not part of our assessment

The **strong signal `[!!]`** appears only with `pogorszył się` (worsened) and when at least one condition is met:
the drop is large relative to the threshold (|Δ| ≥ 2 × threshold), or CUSUM also indicates deterioration.
Without `[!!]`, the `pogorszył się` label is a weaker signal — it may reflect noise or a temporary dip.
Near a threshold, comparisons show one decimal place; if that still hides the difference, `≈` marks approximate values and the explanation states whether the value is below or above the threshold before rounding.
The Δ calculation line also uses `≈` when any displayed value is rounded.

**CUSUM** (Cumulative Sum) is an independent API algorithm that looks at a ~48-hour window. It answers
"is the model changing *now*?", rather than "is it worse than a week ago?". It is shown as context,
not as the main label. A disagreement between CUSUM and the label (for example, `pogorszył się` + `CUSUM:↑`)
means the model declined over the week but recovered slightly in the last 48 hours.

**`SE↕`** appears when the measurement error exceeds 10 — the score is then unreliable and may
vary significantly between benchmark runs.

---

## Polski

CLI do sprawdzania trendów modeli AI na podstawie publicznego API [AI Stupid Meter](https://aistupidlevel.info/).

Porównuje bieżący wynik z 7-dniową średnią i wypisuje krótkie podsumowanie w terminalu.

Vibecoded prototyp.

### Instalacja

```bash
uv tool install /ścieżka/do/tego/repo
```

Albo lokalnie:

```bash
uv sync --dev
```

### Użycie

```bash
aimeter
```

lub w repo:
```bash
uv run aimeter
```

Obsługuje do 2 poziomów verbosity (cokolwiek ponad -vv traktowane jest jak -vv)


Żeby zaktualizować:

```bash
uv tool upgrade aimeter
```

### Testy

```bash
uv run pytest
```

### Wyjście i diagnostyka

Raport trafia na stdout, a błędy i ostrzeżenia API na stderr. Diagnostyka obejmuje
awarie historii (status HTTP, timeout, błędy sieci, JSON-a lub struktury danych),
liczbę odrzuconych punktów, błędne pola leaderboardu i błędy obliczeń.
Ostrzeżenia podają model i pole, gdy są znane, oraz pojawiają się raz, także bez `-v`.

Przy `-v` i `-vv` stderr zawiera też informacje `[INFO]` o braku bieżącego wyniku,
pustej historii lub braku identyfikatora historii. Poprawna pusta historia nie jest
awarią zapytania. Raport zachowuje dostępne wyniki i statystyki historii.
Dotychczasowy komunikat o modelu nieobecnym w leaderboardzie pozostaje w raporcie na stdout.

Kody wyjścia: **0** oznacza odczyt leaderboardu, także przy częściowych wynikach lub
pustej liście modeli; **1** oznacza błąd odczytu lub walidacji leaderboardu;
**2** oznacza błędne argumenty lub konfigurację. Kod 0 nie gwarantuje kompletności danych.
Pusty leaderboard daje ostrzeżenie na stderr i nie tworzy raportu.

Strumienie można zapisać osobno:

```bash
aimeter -v >report.txt 2>diagnostics.txt
```

### Konfiguracja

Własną listę obserwowanych modeli możesz zapisać w pliku TOML, bez edytowania kodu.
Program wybiera konfigurację w następującej kolejności:

1. Plik wskazany przez flagę `--config /ścieżka/do/config.toml`.
2. Plik użytkownika: `$XDG_CONFIG_HOME/aimeter/config.toml`, a jeśli zmienna nie jest
   ustawiona, jest pusta lub zawiera ścieżkę względną — `~/.config/aimeter/config.toml`.
3. Wbudowana lista domyślna, jeśli nie podano `--config` i plik użytkownika nie istnieje.

#### Plik konfiguracyjny

Utwórz katalog `aimeter` w wybranej lokalizacji konfiguracji, a w nim plik
`config.toml`, np.:

```toml
watched_models = [
    "gpt-5.6-sol",
    "gpt-5.5",
    "claude-sonnet-4-6",
    "kimi-k2.7-code",
]
```

**Lista z pliku zastępuje całą listę domyślną**, z zachowaniem podanej kolejności.
Pole `watched_models` jest wymagane i musi być listą niepustych nazw modeli zgodnych
z API. Pusta lista `watched_models = []` oznacza, że żaden model nie jest obserwowany.

Po zapisaniu pliku w lokalizacji użytkownika wystarczy uruchomić `aimeter`
z dowolnego katalogu.

#### Linux, macOS i Windows

Domyślna lokalizacja przy braku `XDG_CONFIG_HOME`:

| System | Przykładowa ścieżka |
|---|---|
| Linux | `/home/uzytkownik/.config/aimeter/config.toml` |
| macOS | `/Users/uzytkownik/.config/aimeter/config.toml` |
| Windows, także przez Git Bash | `C:/Users/uzytkownik/.config/aimeter/config.toml` |

Na Windowsie katalog domowy jest wyznaczany przez Pythona na podstawie `USERPROFILE`
(lub `HOMEDRIVE` i `HOMEPATH`). Jeśli zmieniono `HOME` w Git Bash, bashowe `~` może
wskazywać inne miejsce. Własne `XDG_CONFIG_HOME` na Windowsie podaj jako pełną
ścieżkę Windows, np. `C:/Users/uzytkownik/.config`.

### Jak działa ocena

Wszystko opiera się o tryb **COMBINED** — ten sam, który domyślnie pokazuje wykres na stronie.

Skrypt pobiera z leaderboardu (`sortBy=combined`):
- `currentScore` — bieżący wynik COMBINED
- `trend` — kierunek CUSUM (krótkoterminowy trend z ostatnich ~48h)

**7d średnią i 7d max** liczymy sami z historii wykresu:
`dashboard/history/{id}?period=7d&sortBy=combined` — średnia arytmetyczna i najwyższa wartość punktów `score`
z ostatnich 7 dni (~42 pomiary co 4h). Nie używamy `periodAvg` z API leaderboardu, bo miesza
COMBINED z TOOLING i REASONING i zaniża baseline względem wykresu.

Wyższy wynik oznacza lepszą wydajność — benchmarki mierzą zdolności kodowania.

**Delta** to różnica: `bieżący wynik − 7d średnia COMBINED`. Dodatnia delta = model jest teraz lepszy niż w zeszłym tygodniu.

**Próg** jest wyliczany dynamicznie na podstawie błędu pomiaru (SE liczone z tych samych punktów COMBINED):
`próg = max(5, SE × 0.7)`. Modele z dużym rozrzutem wyników (wysokie SE) dostają wyższy próg,
żeby drobne wahania nie generowały fałszywych alarmów. Minimalna wartość progu to 5.

**Etykieta** jest przypisywana przez porównanie delty z progiem:
- `poprawił się` — delta ≥ +próg
- `pogorszył się` — delta ≤ −próg
- `bez zmian` — delta mieści się w przedziale (−próg, +próg); spadek może być widoczny w Δ, ale nie przekracza szumu pomiarowego
- `brak danych` — brakuje bieżącego wyniku lub użytecznej historii COMBINED 7d albo obliczenia przekraczają zakres liczbowy; wiersz zachowuje dostępne wartości, ale nie pokazuje Δ ani oceny zmiany

Wyniki muszą być skończonymi liczbami. Wartości logiczne i teksty zawierające liczby
traktujemy jako brak danych. Niepoprawne punkty historii są odrzucane; wszystkie
statystyki okresu korzystają z tego samego zbioru pozostałych punktów. Pusta historia
lub historia bez poprawnych punktów nie daje podstawy do porównania.

Brakujący lub niepoprawny `trend` pokazujemy jako `Cumul. sum:?` (nieznany),
a jawne `stable` jako `→`. Nieznany trend nie blokuje silnego sygnału wynikającego
z wystarczająco dużego spadku. Niepoprawne opcjonalne metadane są pomijane.

**`-vv`** — dwa rodzaje liczb w jednej linii:
- **COMBINED 7d** (punkty, CI) — liczone lokalnie z historii wykresu, na tym samym zbiorze co Δ i SE
- **stabilność (API)** — pole `stability` z leaderboardu; serwer liczy je własną metodą, nie wiemy dokładnie z czego, więc to tylko kontekst pomocniczy, nie część naszej oceny

**Silny sygnał `[!!]`** — pojawia się tylko przy `pogorszył się` i gdy spełniony jest co najmniej jeden warunek:
duży spadek względem progu (|Δ| ≥ 2 × próg) albo CUSUM też wskazuje na pogorszenie.
Bez `[!!]` etykieta `pogorszył się` jest słabszym sygnałem — może być szum lub chwilowy dip.
Przy granicy progu porównania pokazują jedno miejsce po przecinku; jeśli nadal ukrywa to różnicę, `≈` oznacza wartości przybliżone, a opis wyjaśnia, czy wynik jest poniżej czy powyżej progu przed zaokrągleniem.
Linia obliczania Δ również używa `≈`, jeśli którakolwiek pokazana wartość jest zaokrąglona.

**CUSUM** (Cumulative Sum) to niezależny algorytm API patrzący w okno ~48h. Odpowiada na pytanie
"czy model zmienia się *teraz*?", nie "czy jest gorszy niż tydzień temu?". Pokazywany jako kontekst,
nie jako główna etykieta. Sprzeczność CUSUM z etykietą (np. `pogorszył się` + `CUSUM:↑`) oznacza
że model spadł w ciągu tygodnia, ale w ostatnich 48h lekko odbił.

**`SE↕`** pojawia się gdy błąd pomiaru przekracza 10 — wynik jest wtedy mało wiarygodny i może
znacznie różnić się między kolejnymi uruchomieniami benchmarku.
