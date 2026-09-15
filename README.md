# aimeter

CLI do sprawdzania trendów modeli AI na podstawie publicznego API [AI Stupid Meter](https://aistupidlevel.info/).

Porównuje bieżący wynik z 7-dniową średnią i wypisuje krótkie podsumowanie w terminalu.

Vibecoded prototyp.

## Instalacja

```bash
uv tool install /ścieżka/do/tego/repo
```

Albo lokalnie:

```bash
uv sync --dev
```

## Użycie

```bash
aimeter
```

lub w repo:
```bash
uv run aimeter
```

Obsługuje do 2 poziomów verbosity (cokolwiek ponad -vv traktowane jest jak -vv)


W przypadku aktualizacji należy użyć:

```bash
uv tool upgrade aimeter
```

## Testy

```bash
uv run pytest
```

## Konfiguracja

Własną listę obserwowanych modeli możesz zapisać w pliku TOML, bez edytowania kodu.
Program wybiera konfigurację w następującej kolejności:

1. Plik wskazany przez flagę `--config /ścieżka/do/config.toml`.
2. Plik użytkownika: `$XDG_CONFIG_HOME/aimeter/config.toml`, a jeśli zmienna nie jest
   ustawiona, jest pusta lub zawiera ścieżkę względną — `~/.config/aimeter/config.toml`.
3. Wbudowana lista domyślna, jeśli nie podano `--config` i plik użytkownika nie istnieje.

### Plik konfiguracyjny

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

### Linux, macOS i Windows

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

## Jak działa ocena

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
- `brak danych` — nie udało się pobrać historii COMBINED 7d; wiersz pokazuje bieżący wynik i CUSUM z API, ale bez Δ i bez oceny

**`-vv`** — dwa rodzaje liczb w jednej linii:
- **COMBINED 7d** (punkty, CI) — liczone lokalnie z historii wykresu, na tym samym zbiorze co Δ i SE
- **stabilność (API)** — pole `stability` z leaderboardu; serwer liczy je własną metodą, nie wiemy dokładnie z czego, więc to tylko kontekst pomocniczy, nie część naszej oceny

**Silny sygnał `[!!]`** — pojawia się tylko przy `pogorszył się` i gdy spełniony jest co najmniej jeden warunek:
duży spadek względem progu (|Δ| ≥ 2 × próg) albo CUSUM też wskazuje na pogorszenie.
Bez `[!!]` etykieta `pogorszył się` jest słabszym sygnałem — może być szum lub chwilowy dip.

**CUSUM** (Cumulative Sum) to niezależny algorytm API patrzący w okno ~48h. Odpowiada na pytanie
"czy model zmienia się *teraz*?", nie "czy jest gorszy niż tydzień temu?". Pokazywany jako kontekst,
nie jako główna etykieta. Sprzeczność CUSUM z etykietą (np. `pogorszył się` + `CUSUM:↑`) oznacza
że model spadł w ciągu tygodnia, ale w ostatnich 48h lekko odbił.

**`SE↕`** pojawia się gdy błąd pomiaru przekracza 10 — wynik jest wtedy mało wiarygodny i może
znacznie różnić się między kolejnymi uruchomieniami benchmarku.
