# Współbieżność w Pythonie: Threading vs Multiprocessing vs Asyncio

## Problem: Python domyślnie robi jedną rzecz na raz

Kiedy potrzebujesz zrobić wiele rzeczy "jednocześnie" (np. pobrać 100 stron internetowych, przetworzyć 100 obrazów), masz **trzy klasyczne podejścia** — plus jedno wschodzące czwarte (Python bez GIL-a, patrz koniec).

Wszystkie trzy działają pod wspólnym, ujednoliconym API: [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html), które udostępnia `ThreadPoolExecutor` i `ProcessPoolExecutor` z tym samym interfejsem. `asyncio` to oddzielny świat, ale integruje się z obydwoma przez `asyncio.to_thread()` i `loop.run_in_executor()`.

## Model myślowy: gdzie faktycznie odbywa się praca?

Każda decyzja dotycząca współbieżności zależy od jednego pytania: **gdzie twój program spędza czas zegarowy?**

| Typ pracy   | Czas spędzony w…                                  | Wąskie gardło                        | Narzędzie         |
| ----------- | ------------------------------------------------- | ------------------------------------ | ----------------- |
| I/O-bound   | Wywołania systemowe kernela, oczekiwanie na gniazda/dysk | Opóźnienia, współbieżne deskryptory plików | threading, asyncio |
| CPU-bound   | Bytecode Pythona, kernele NumPy, regex, parsowanie JSON | GIL serializuje bytecode         | multiprocessing   |
| Mieszany    | Oba, często w tym samym zadaniu                   | To co dominuje                       | asyncio + ProcessPool |

Jeśli twoja gorąca ścieżka zwalnia GIL (NumPy BLAS, syscalle I/O, hashlib, zlib, większość rozszerzeń C), threading zachowuje się prawie jak prawdziwy równoległy. Jeśli nie (czyste pętle Pythona, operacje na słownikach/listach), tylko procesy się skalują.

---

## 1. Wielowątkowość (`threading`)

**Czym jest:** Wiele wątków w jednym procesie. Wątki dzielą tę samą pamięć.

```python
from concurrent.futures import ThreadPoolExecutor
import httpx

urls = ["http://a.com", "http://b.com", "http://c.com"]

# Ponowne użycie jednego klienta — pula połączeń, jeden handshake TLS na host.
with httpx.Client(timeout=10.0) as client:
    def fetch(url: str) -> str:
        return client.get(url).text  # blokuje na sieci

    # max_workers=3 tutaj tylko dla demonstracji; domyślna wartość biblioteki to
    # min(32, os.cpu_count() + 4), co jest zwykle dobrym punktem startowym dla I/O.
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, urls))
```

### Analogia
> Jeden kucharz (CPU) z trzema palnikami. Stawia garnek na jednym, czeka aż się zagotuje → skacze do następnego. Nie gotuje szybciej, ale nie traci czasu na czekanie.

### Kluczowa rzecz — GIL (Global Interpreter Lock)
Blokada Pythona, która zapewnia, że **tylko jeden wątek wykonuje bytecode Pythona** w danym momencie na klasycznej wersji CPython. Wątki się przełączają (interpreter wywłaszcza co ~5 ms), ale faktycznie nie działają równolegle na CPU-bound kodzie Pythona.

> **Uwaga 2026:** Od Pythona 3.13 istnieje wersja bez GIL-a (PEP 703, `--disable-gil`). Zobacz ostatnią sekcję.

### ✅ Zalety
- Prosty — to samo API co kod synchroniczny, tylko równoległy
- Świetny gdy program czeka (sieć, dysk, baza danych) — **I/O-bound**
- Współdzielona pamięć — łatwa (ale niebezpieczna) komunikacja między wątkami
- `concurrent.futures.ThreadPoolExecutor` jest gotowy do produkcji od razu
- Skaluje się do kilkuset workerów dla I/O bez problemu

### ❌ Wady
- GIL blokuje prawdziwy równoległy na CPU-bound kodzie Pythona
- **Wyścigi (Race conditions)** — dwa wątki modyfikujące ten sam obiekt jednocześnie; wywłaszczenie może nastąpić między dowolnymi dwoma bytecodes
- Trudny do debugowania — niedeterministyczne przeplatanie
- Wymagane prymitywy synchronizacji (`threading.Lock`, `queue.Queue`, `threading.Event`)

### 🎯 Kiedy używać
Wiele operacji I/O, **dziesiątki do kilkuset** współbieżnych zadań: pobieranie stron, zapytania do bazy, odczyt plików. Sensowny domyślny wybór gdy obciążenie jest blokujące i nie chcesz przepisywać wszystkiego jako `async`.

---

## 2. Wieloprocesorowość (`multiprocessing`)

**Czym jest:** Wiele oddzielnych procesów, każdy z własnym interpreterem Pythona i własną pamięcią. **Omija GIL.**

```python
from concurrent.futures import ProcessPoolExecutor

def heavy_compute(n: int) -> int:
    return sum(i * i for i in range(n))  # CPU-ciężkie

# KRYTYCZNE na Windows / macOS (metoda startowa spawn):
# bez tego zabezpieczenia, procesy potomne będą ponownie importować moduł i
# rekursywnie tworzyć kolejne procesy — RuntimeError.
if __name__ == "__main__":
    data = [10_000_000, 20_000_000, 30_000_000]

    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(heavy_compute, data))
```

### Analogia
> Trzech oddzielnych kucharzy, każdy z własną kuchnią. Gotują **naprawdę** jednocześnie. Ale żeby podzielić się składnikami, muszą je zapakować i przenosić między kuchniami.

### ✅ Zalety
- **Prawdziwy równoległy** — używa wielu rdzeni CPU
- Omija GIL
- Izolacja — awaria jednego procesu nie zabija reszty
- To samo API `concurrent.futures` co wątki — zmień jedną linię żeby przełączyć

### ❌ Wady
- Narzut uruchamiania zależy od metody startowej:
  - `fork` (dawny domyślny Linux): ~1–10 ms, ale **niebezpieczny przy mieszaniu z wątkami**. Emituje `DeprecationWarning` od 3.12; domyślny Linux przechodzi od niego w 3.14+
  - `spawn` (domyślny Windows/macOS, bezpieczny wszędzie): 50–500 ms, każdy proces ponownie importuje moduły
  - `forkserver` (staje się domyślnym dla Linux): kompromis, zalecany dla kodu mieszającego wątki z pulami procesów
- IPC jest drogie — argumenty i wartości zwracane muszą być **spickled** i kopiowane w obu kierunkach
- Nie każdy obiekt jest piklowalny (lambdy, funkcje lokalne, otwarte uchwyty plików, połączenia DB)
- Rzadko właściwe narzędzie dla czystego I/O — współbieżność jest ograniczona przez `cpu_count()` i narzut się sumuje
- Wymaga zabezpieczenia `if __name__ == "__main__"` na Windows/macOS (i wszędzie używając `spawn`)
- Logowanie wymaga jawnej konfiguracji per proces — zazwyczaj `QueueHandler` + jeden wątek nasłuchujący w rodzicu
- Domyślne `max_workers = os.cpu_count()`
- Wskazówka: dla IPC bez kopiowania z tablicami NumPy/tensorami, patrz `multiprocessing.shared_memory` (3.8+)

### 🎯 Kiedy używać
Praca CPU-bound: przetwarzanie obrazów, potoki NumPy/pandas, ekstrakcja cech ML, kryptografia, parsowanie, kompilacja. Również odpowiednie dla **mieszanych obciążeń** gdzie każda jednostka pracy jest zarówno ciężka jak i wykonuje trochę I/O.

W ekosystemie data-science, **`joblib`** (zbudowany na `loky`) jest de-facto wrapperem — lepsze pikle (cloudpickle) i bardziej sensowne zarządzanie semaforami niż standardowy `multiprocessing`.

---

## 3. Asyncio (`asyncio`)

**Czym jest:** Jeden wątek z pętlą zdarzeń. Kod jawnie oddaje sterowanie przy `await` żeby pętla mogła w tym czasie uruchomić coś innego. Zbudowane na `async`/`await`.

```python
import asyncio
import httpx

async def fetch(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)  # oddaje sterowanie pętli zdarzeń
    return response.text

async def main() -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        # TaskGroup (Python 3.11+) — preferowany nad asyncio.gather:
        # jeśli jedno zadanie rzuca wyjątek, siostry są czysto anulowane (ExceptionGroup).
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(fetch(client, url)) for url in urls]
        # Wszystkie zadania są tu gwarantowanie ukończone; bezpiecznie czytać .result().
        return [t.result() for t in tasks]

results = asyncio.run(main())
```

> **Wskazówka:** dla długo działających serwisów, które uruchamiają pętlę raz, preferuj `asyncio.Runner()` (3.11+) — daje jawny cykl życia, stabilny kontekst `ContextVar` przez wywołania `run()`, i czystsze zamykanie niż wielokrotne wywoływanie `asyncio.run`.

### Producent/konsument z `asyncio.Queue`

Kanoniczny wzorzec backpressure — ograniczona kolejka między producentem fan-out a pulą workerów stałego rozmiaru. Komponuje się lepiej niż ad-hoc `gather` + `Semaphore` gdy potok ma więcej niż jeden etap.

```python
async def producer(queue: asyncio.Queue[str], urls: list[str]) -> None:
    for url in urls:
        await queue.put(url)  # blokuje gdy kolejka jest pełna — naturalne backpressure
    for _ in range(N_WORKERS):
        await queue.put(None)  # sentinel per worker

async def worker(queue: asyncio.Queue[str], client: httpx.AsyncClient) -> None:
    while (url := await queue.get()) is not None:
        try:
            await client.get(url, timeout=10)
        finally:
            queue.task_done()

async def main(urls: list[str]) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
    async with httpx.AsyncClient() as client, asyncio.TaskGroup() as tg:
        tg.create_task(producer(queue, urls))
        for _ in range(N_WORKERS):
            tg.create_task(worker(queue, client))
```

### Łączenie z kodem synchronicznym

Asyncio jest jednowątkowe, więc jedno blokujące wywołanie zamraża **wszystko**. Użyj `asyncio.to_thread()` (3.9+) dla blokującego I/O i `run_in_executor()` z `ProcessPoolExecutor` dla pracy CPU:

```python
from pathlib import Path

# Blokujące I/O z kontekstu async — odciąż do wątku.
# Przekaż callable — NIE wywołuj go z góry (częsty błąd).
data = await asyncio.to_thread(Path("big.log").read_text)

# Praca CPU-bound z kontekstu async — odciąż do procesu:
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(process_pool, heavy_compute, 10_000_000)
```

### Timeouty, anulowanie i backpressure

Trzy rzeczy, które gryzą każdy prawdziwy kod asyncio:

```python
# Timeouty (3.11+): anuluje blok po wygaśnięciu, rzuca TimeoutError.
async with asyncio.timeout(5):
    await fetch(client, url)

# Backpressure: 10_000 zadań = 10_000 otwartych gniazd. Ogranicz współbieżność.
sem = asyncio.Semaphore(100)
async def fetch_bounded(url: str) -> str:
    async with sem:
        return await fetch(client, url)

# Anulowanie jest częścią kontraktu: nigdy nie łap nagiego `except Exception`
# bez ponownego rzucania CancelledError.
try:
    await something()
except asyncio.CancelledError:
    # posprzątaj, a potem:
    raise
except Exception:
    ...
```

### Analogia
> Jeden kucharz, ale **super zorganizowany**. Stawia garnek, natychmiast kroi warzywa, natychmiast nastawia wodę do gotowania. Nigdy nie stoi bezczynnie. Jeden kucharz robi pracę trzech, bo nie traci ani sekundy na czekanie.

### ✅ Zalety
- **Najbardziej wydajny dla I/O** — dziesiątki tysięcy połączeń w jednym wątku
- Coroutines są małe — ~2 KB każda vs ~8 MB domyślny stos na wątek OS
- **Brak wyścigów na poziomie bytecode** — przełączanie kontekstu tylko przy `await` (ale patrz Wady)
- Standard w nowoczesnym Pythonie (FastAPI, aiohttp, httpx, asyncpg, SQLAlchemy 2.x async)
- Ustrukturyzowana współbieżność przez `TaskGroup` + `ExceptionGroup` jest pierwszoklasowa od 3.11

### ❌ Wady
- **Wirusowe / wszystko albo nic** — gdy funkcja jest `async`, każdy wywołujący w górę łańcucha musi być `async` (lub używać `asyncio.run`/`to_thread`)
- **Logiczne wyścigi nadal istnieją** — między punktami `await`, inna coroutine może mutować współdzielony stan. Możesz nadal potrzebować `asyncio.Lock`.
- Stromsza krzywa uczenia (pętla zdarzeń, zadania, anulowanie, grupy wyjątków)
- Bezużyteczny dla CPU-bound — gorąca pętla blokuje całą pętlę zdarzeń
- Podzielony ekosystem bibliotek — `requests` jest sync, potrzebujesz `httpx`/`aiohttp`; wiele sterowników DB ma oddzielne warianty sync/async

> **Alternatywy:** `trio` (ustrukturyzowana współbieżność od samego początku) i `anyio` (przenośna abstrakcja nad asyncio/trio) warto znać dla autorów bibliotek.

### 🎯 Kiedy używać
Masowe operacje sieciowe — API, websockety, serwery web, scrapery z tysiącami współbieżnych połączeń. Domyślny wybór dla nowych serwisów intensywnie korzystających z sieci.

---

## Głębsze zagłębienie

Trzy tematy, które krótka forma powyżej pomija, ale każdy ekspert musi je przyswoić. Są to najczęstsze problemy produkcyjne — pomiń przy pierwszym czytaniu jeśli dopiero oswajasz się z podstawami.

### 1. Mechanizm asyncio i pułapka task-gc

Pod maską `asyncio` to pętla selektora (epoll na Linux, kqueue na BSD/macOS, IOCP na Windows) sterująca kolejką callbacków. Kluczowa hierarchia obiektów:

- **Coroutine** — zawieszona funkcja, zbudowana z `async def`. Nieaktywna dopóki nie jest oczekiwana lub opakowana w Task. Sama nie ma harmonogramu.
- **Future** — niskopoziomowy placeholder dla wyniku. Ustawiany przez pętlę lub obcy kod (np. `run_coroutine_threadsafe`).
- **Task** — `Future`, który *napędza* coroutine. Tworzony przez `asyncio.create_task()` / `TaskGroup.create_task()`. Harmonogramuje się na pętli.

Pętla uruchamia callbacki dopóki żaden nie jest gotowy, potem blokuje w selektorze dopóki deskryptor pliku lub timer nie odpali. `call_soon` wstawia callback do kolejki na następną iterację; `call_later`/`call_at` harmonogramuje go na monotonicznym zegarze pętli.

**Pułapka task-gc.** Ten kod ma błąd:

```python
async def spawn_background_work():
    asyncio.create_task(do_something())  # ❌ wartość zwracana odrzucona
```

`create_task` zwraca Task, który pętla trzyma **słabą referencją**. Jeśli nic innego nie trzyma silnej referencji, garbage collector może (i w końcu to zrobi) zebrać Task *w trakcie działania*, anulując go cicho z enigmatycznym ostrzeżeniem "Task was destroyed but it is pending!" na stderr. Naprawienie:

```python
_background_tasks: set[asyncio.Task] = set()

def spawn(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
```

Lepiej: używaj `TaskGroup` żeby czas życia był jawny i ograniczony. Jeśli utrzymujesz `set` zadań w tle, to zazwyczaj sygnał — twoja współbieżność jest nieustrukturyzowana.

**`contextvars`** (PEP 567) to asynchroniczny natywny zamiennik thread-local storage. Każde zadanie dostaje kopię kontekstu wywołującego przy tworzeniu — krytyczne dla stanu o zasięgu żądania (ID użytkownika, ID śledzenia, transakcja DB) w asynchronicznych frameworkach web.

### 2. Anulowanie: kontrakt, który wszyscy dostają źle

Anulowanie jest **kooperatywne** i **oparte na wyjątkach** w asyncio. `task.cancel()` harmonogramuje `CancelledError` do rzucenia przy następnym punkcie `await` wewnątrz coroutine. Od Pythona 3.8, `CancelledError` dziedziczy po `BaseException`, *nie* `Exception` — właśnie po to, żeby naiwne handlery go nie połknęły:

```python
try:
    await something()
except Exception:  # ✅ nie łapie CancelledError — dobrze
    log_and_continue()
```

Trzy zasady:

1. **Nigdy nie połykaj `CancelledError` bez ponownego rzucania.** Jeśli musisz posprzątać, zrób to, potem `raise`. W przeciwnym razie anulowanie jest utracone i ktokolwiek cię wywołał czeka wiecznie.
2. **Shielding to narzędzie, nie domyślne.** `await asyncio.shield(critical_cleanup())` chroni wewnętrzną coroutine przed zewnętrznym anulowaniem, ale zewnętrzne anulowanie nadal propaguje do samego shielda — więc potrzebujesz dyscypliny `try/finally` wokół niego.
3. **TaskGroups anulują rodzeństwo przy pierwszej awarii.** Jeśli zadanie A rzuca, grupa anuluje B, C, D i agreguje wszystko w `ExceptionGroup` (PEP 654). Użyj `except* SomeError:` do obsługi konkretnych gałęzi.

**Łagodne zamykanie** to miejsce gdzie anulowanie spotyka się z rzeczywistością: SIGTERM → pętla odbiera sygnał → wszystkie zadania anulowane → oczekujące I/O spływa → proces wychodzi. Szablon:

```python
async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def server_with_shutdown():
        # serve() powinno kooperatywnie obserwować `stop` i czysto wracać.
        server_task = asyncio.create_task(serve(stop))
        await stop.wait()
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task

    async with asyncio.TaskGroup() as tg:
        tg.create_task(server_with_shutdown())
```

Unikaj `raise asyncio.CancelledError` wewnątrz bloku `TaskGroup`: jest konwertowane w `BaseExceptionGroup`, który wycieka poza `async with`. Preferuj jawne `Event` + anulowanie wewnętrznego zadania, lub normalny return gdy `stop` jest ustawiony.

To jest wzorzec za `uvicorn --graceful-timeout`, hookami preStop Kubernetes, i praktycznie każdym produkcyjnym serwisem async.

### 3. Kiedy wątki są jednak równoległe: zwalnianie GIL w rozszerzeniach C

Mantra "wątki nie parallelizują na CPU-bound Pythonie" jest prawdziwa *dla czystego bytecodu Pythona*. GIL jest trzymany przez pętlę eval interpretera — ale każde rozszerzenie C może je zwolnić przez `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` wokół kodu, który nie dotyka obiektów Pythona.

Konkretnie, te zwalniają GIL i **faktycznie** się parallelizują między wątkami:

| Operacja                                         | GIL zwolniony | Dlaczego to ważne                        |
| ------------------------------------------------ | ------------- | ---------------------------------------- |
| `numpy` zwektoryzowane operacje na dużych tablicach (BLAS) | tak  | threading skaluje się liniowo na matematyce macierzowej |
| `numpy` ufuncs, FFT, algebra liniowa             | tak           | j.w.                                     |
| `hashlib` (sha256, blake2, …) na dużych buforach | tak (≥ `HASHLIB_GIL_MINSIZE`, ~2 KB) | równoległe hashowanie faktycznie działa |
| `zlib`, `bz2`, `lzma` kompresja/dekompresja     | tak           | równoległa kompresja                     |
| zapytania `sqlite3` (tryb serializowany)         | tak           | równoległa praca z DB                    |
| I/O pliku (`read`/`write`), I/O gniazd          | tak           | dlatego threading działa dla I/O        |
| operacje `Pillow` na obrazach (większość)        | tak           | równoległe potoki obrazów               |
| parsowanie `lxml`                                | tak           | równoległy XML                           |
| `cryptography` / prymitywy OpenSSL              | tak           | równoległy TLS, AES, RSA                |
| kernele obliczeniowe `pyarrow`                   | tak           | równoległe operacje kolumnowe           |
| `re.match` / regex                               | **nie**       | czyste C ale trzyma GIL                 |
| `json.loads` / `json.dumps`                      | **nie**       | j.w.                                    |
| Czysto-Pythonowa pętla `for`, operacje na dict/list | **nie**   | bytecode pod GIL                        |

Praktyczna konsekwencja: obciążenie ciężkie NumPy często **nie** potrzebuje multiprocessing. Benchmark przed sięgnięciem po procesy — na 8-rdzeniowym komputerze, `ThreadPoolExecutor` + NumPy może dorównać `ProcessPoolExecutor` z zerowym narzutem pikle.

Uważaj na **uszkodzenie copy-on-write z `fork`**: licznik referencji CPython siedzi wewnątrz nagłówka każdego obiektu, więc nawet *czytanie* obiektu (które zwiększa licznik referencji) brudzi strony pamięci i niszczy CoW. Pre-fork workery webowe (gunicorn), które oczekują współdzielenia dużego modelu w pamięci, często kończą z N kopiami i tak. PEP 683 (nieśmiertelne obiekty, 3.12+) pomaga tylko dla wąskiego zestawu singletonów — `None`, `True`/`False`, małe inty, internowane stringi — nie twoje moduł-poziomowe tuple, dicts, czy załadowane wagi ML.

---

## Częste pułapki

| Pułapka | Objaw | Naprawa |
|---|---|---|
| `time.sleep(5)` wewnątrz coroutine | Cała pętla zdarzeń zamrożona | `await asyncio.sleep(5)` |
| Zapomniany `await` | Zwraca obiekt coroutine, żadna praca nie wykonana | Lint z `ruff`/`mypy`; dodaj `await` |
| `asyncio.gather` + wyjątek | Siostry działają dalej, czyszczenie pominięte | Użyj `asyncio.TaskGroup` (3.11+) |
| Brak `if __name__ == "__main__":` | Nieskończone tworzenie procesów na Win/macOS | Dodaj zabezpieczenie |
| Pikle lambdy w `ProcessPoolExecutor` | `PicklingError` | Użyj funkcji na poziomie modułu |
| Współdzielenie połączenia DB między procesami | Uszkodzony stan, zablokowane uchwyty | Otwieranie jednego per proces |
| Mutowanie dicta z wielu wątków | Ciche uszkodzenie danych | `threading.Lock` lub `queue.Queue` |
| Blokujące wywołanie w kodzie async (np. `requests.get`) | Pętla zdarzeń zatrzymuje się | `await asyncio.to_thread(...)` lub przejście na async klienta |
| Wywoływanie funkcji wewnątrz `asyncio.to_thread(fn())` | Uruchamia się na pętli zdarzeń i tak | Przekaż callable: `to_thread(fn)` |
| Połykanie `CancelledError` przez `except Exception` | Zadania nie mogą być anulowane, zawieszenie przy zamykaniu | Łap i ponownie rzuć `CancelledError` |
| Nieograniczony `TaskGroup` / `gather` nad N wejściami | Wyczerpanie gniazd/FD, przepełnienie pamięci | `asyncio.Semaphore(limit)` |
| Używanie metody startowej `fork` z wątkami | Zakleszczenia, uszkodzony stan | Użyj `forkserver` lub `spawn` (`mp.get_context("forkserver")`) |
| Kolizje logowania per-process | Przeplatane/utracone linie logów | `QueueHandler` w workerach, jeden listener w rodzicu |

---

## Podsumowanie

|                     | **Threading**                      | **Multiprocessing**   | **Asyncio**                 |
| ------------------- | ---------------------------------- | --------------------- | --------------------------- |
| **Równoległy**      | wywłaszczający, serializowany przez GIL | prawdziwy równoległy | kooperatywny (jeden wątek) |
| **Najlepszy dla**   | I/O (dziesiątki)                   | CPU-bound             | I/O (tysiące+)              |
| **Narzut**          | średni (~8 MB/wątek)               | wysoki (~30–100 MB/proc) | mały (~2 KB/coroutine)   |
| **Trudność**        | średnia                            | średnia               | wysoka                      |
| **Wyścigi danych**  | tak                                | brak współdzielonego stanu domyślnie (wyścigi wracają jeśli zdecydujesz się na `shared_memory`/`Manager`) | brak niskopoziomowych; logiczne wyścigi przy punktach `await` |
| **Model pamięci**   | współdzielona                      | oddzielna + IPC       | współdzielona (jeden wątek) |
| **Ujednolicone API** | `concurrent.futures`              | `concurrent.futures`  | `asyncio` + pętla zdarzeń  |

---

## Przybliżona intuicja benchmarków

*Pobieranie 1000 URL-i (~100 ms opóźnienia każdy), jeden komputer:*

| Podejście                    | Czas zegara | Uwagi                                  |
| ---------------------------- | ----------- | -------------------------------------- |
| Sekwencyjny `requests`       | ~100 s      | Baseline                               |
| `ThreadPoolExecutor(50)`     | ~2–3 s      | Ograniczony przez liczbę wątków i pamięć |
| `asyncio` + `httpx`          | ~1 s        | Skaluje się do 10k+ połączeń trivialnie |
| `ProcessPoolExecutor(8)`     | ~13 s       | Każdy z 8 workerów blokuje sekwencyjnie na sieci (1000 ÷ 8 × 0.1 s) bo `requests` jest synchroniczne; IPC dodaje na wierzch — złe narzędzie dla czystego I/O |

*Liczby są ilustracyjne — zmierz swoje własne obciążenie.*

---

## Drzewo decyzyjne

```
Czego masz dużo?
├── Czekania (sieć, dysk, baza danych) → I/O-bound
│   ├── Dziesiątki zadań              → threading
│   └── Setki / tysiące               → asyncio
├── Mieszane (I/O + CPU per element)  → asyncio + run_in_executor(ProcessPool)
└── Obliczeń (matematyka, ML, obrazy) → CPU-bound
    └── multiprocessing (lub Python bez GIL na 3.13+)
```

---

## 🆕 Przyszłość: dwie równoległe ścieżki poza GIL-em

### Python bez GIL-a (PEP 703)

Od **Pythona 3.13** istnieje opcjonalna wersja bez GIL-a (`python3.13t`, flaga `--disable-gil`). W tym trybie wątki **naprawdę** uruchamiają kod Pythona równolegle — `threading` staje się opłacalne dla pracy CPU-bound.

Stan na 2026:
- **Eksperymentalny**, opcjonalny. Narzut jednowątkowy był zauważalny na 3.13 (10–40% na niektórych obciążeniach z powodu tendencyjnego liczenia referencji + wyłączonej specjalizacji); znacznie poprawiony na 3.14.
- Ekosystem rozszerzeń C nadal dociąga (NumPy, Pillow, lxml dostarczają koła bez GIL-a; długi ogon zostaje)
- Oczekiwane stanie się domyślnym gdzieś około Pythona 3.15–3.16

### Per-interpreter GIL / subinterpretery (PEP 684, PEP 734)

Od **Pythona 3.12** każdy subinterpretator ma swój własny GIL, a 3.13+ udostępnia API na poziomie Pythona. Python **3.14** dodaje `concurrent.futures.InterpreterPoolExecutor` — zamiennik kuzyna `ProcessPoolExecutor` ale z izolacją podobną do procesów przy koszcie podobnym do wątków (bez fork, bez pełnego bootstrapu interpretera).

To trzeci punkt w przestrzeni projektowej:

|                        | Wątki | Subinterpretery | Procesy |
| ---------------------- | ----- | --------------- | ------- |
| Prawdziwy równoległy (GIL) | nie (do 3.13t) | tak         | tak     |
| Współdzielenie pamięci | pełne | żadne (z założenia) | żadne |
| Koszt startowy         | µs    | ms              | dziesiątki–setki ms |
| Transfer danych        | bezpośredni | kanały / pickle | pickle + IPC |

Na dziś w produkcji: zakładaj że GIL istnieje. Ale wiedz że oba wyjścia ewakuacyjne dojrzewają szybko.

---

## 💬 Na rozmowie kwalifikacyjnej

> "Threading i asyncio rozwiązują problem **I/O-bound** — threading jest prostszy i integruje się z bibliotekami blokującymi, asyncio jest bardziej wydajny w skali i jest nowoczesnym domyślnym dla serwisów sieciowych. Multiprocessing rozwiązuje **CPU-bound**, bo omija GIL i daje prawdziwy równoległy — kosztem narzutu IPC i ograniczeń pikle.
>
> W praktyce: **FastAPI = asyncio**, **przetwarzanie danych = multiprocessing**, **proste skrypty scrapujące = threading**. A mieszane obciążenia to zazwyczaj asyncio z `ProcessPoolExecutor` podpiętym do `run_in_executor` dla gorącej ścieżki.
>
> Patrząc w przyszłość, Python bez GIL-a (PEP 703, 3.13+) w końcu uczyni threading konkurencyjnym dla pracy CPU-bound też — ale to jeszcze nie jest gotowe produkcyjnie."

---

## Mieszane obciążenie: asyncio + ProcessPool od końca do końca

Rzeczywisty wzorzec: pobierz wiele stron jednocześnie (I/O), potem uruchom drogie czystopythonowe transformacje na każdej (CPU). Jedno narzędzie jest złe dla obu połówek — połącz je.

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor
import httpx

def extract_features(html: str) -> dict:
    # Udawaj że to jest ciężkie: tokenizacja, parsowanie, regex, cokolwiek.
    return {"len": len(html), "words": len(html.split())}

async def process(url: str, client: httpx.AsyncClient,
                  pool: ProcessPoolExecutor, sem: asyncio.Semaphore) -> dict:
    async with sem:  # backpressure na współbieżność sieci
        r = await client.get(url, timeout=10)
    loop = asyncio.get_running_loop()
    # Gorąca ścieżka CPU odciążona do oddzielnego procesu — pętla zdarzeń pozostaje wolna.
    return await loop.run_in_executor(pool, extract_features, r.text)

async def main(urls: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(100)
    with ProcessPoolExecutor() as pool:  # domyślnie os.cpu_count()
        async with httpx.AsyncClient() as client:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(process(url, client, pool, sem))
                         for url in urls]
            return [t.result() for t in tasks]

if __name__ == "__main__":
    asyncio.run(main([...]))
```

Kluczowe punkty: `asyncio` zarządza I/O i orkiestracją; `ProcessPoolExecutor` zarządza rdzeniami; `Semaphore` ogranicza fan-out; `TaskGroup` daje ustrukturyzowane anulowanie. Ta kompozycja skaluje się od jednego komputera do produkcyjnego potoku pozyskiwania danych.

---

## Ścieżka do ekspertyzy: tematy do opanowania

Trzy sekcje powyżej to rdzeń. To co oddziela "zna współbieżność" od "uruchamia produkcyjne systemy współbieżne" to lista poniżej. Traktuj ją jako curriculum — każdy punkt to mniej więcej jedno popołudnie czytania + eksperymentowania.

### Podstawy

- **Model pamięci Pythona i atomowość** — które bytecodes są atomowe (`a = b`, `d[k] = v` na wbudowanym dict) a które nie (`a += 1`, `d.setdefault` w starszych wersjach). Interwał przełączania (`sys.setswitchinterval`, domyślnie 5 ms) wywłaszcza między bytecodes, nie wewnątrz nich.
- **Prymitywy synchronizacji w głąb** — `Lock` vs `RLock` (reentrancja), `Semaphore` vs `BoundedSemaphore`, `Event`, `Condition`, `Barrier`. Kolejność blokad zapobiegająca zakleszczeniom. **Preferuj `queue.Queue` nad jawnymi blokadami** — to kanoniczny thread-safe prymityw przekazywania wiadomości.
- **Ustrukturyzowana współbieżność jako paradygmat** — dlaczego istnieje `trio` (nurseries, cancel scopes), dlaczego "fire and forget" to antywzorzec, Rob Pike "concurrency is not parallelism".
- **Generatory i menedżery kontekstu async** — `async for`, `async with`, `@asynccontextmanager`, semantyka `aclose()`, dlaczego czyszczenie generatora async było błędne przed 3.10.

### Zachowanie w czasie wykonywania

- **Mechanizm pętli zdarzeń** — selektory (epoll/kqueue/IOCP), `call_soon` vs `call_later` vs `call_at`, dlaczego `time.sleep` blokuje wszystko, niezmiennik jednego wątku.
- **`contextvars` (PEP 567)** — async-natywny zamiennik `threading.local`. Każde Task dziedziczy migawkę kontekstu. Krytyczne dla stanu o zasięgu żądania (ID śledzenia, auth, transakcje DB) we frameworkach ASGI.
- **Sygnały + wątki + async** — tylko główny wątek obsługuje sygnały; `loop.add_signal_handler` to async-bezpieczne API; łagodne zamykanie w kontenerach (SIGTERM → drain → exit).
- **Interop: sync ↔ async** — `asyncio.run_coroutine_threadsafe`, `loop.call_soon_threadsafe`, `janus.Queue` do mostkowania wątków i async. `nest_asyncio` istnieje ale zazwyczaj to sygnał — zbadaj prawdziwy problem architektoniczny.

### Umiejętności produkcyjne

- **Obserwowalność dla współbieżności** — `PYTHONASYNCIODEBUG=1`, `loop.slow_callback_duration`, `faulthandler` dla diagnozy zakleszczeń, `py-spy` (profilowanie próbkujące, widzi stosy async bez instrumentacji), propagacja kontekstu OpenTelemetry async.
- **Pomiar wydajności** — latencja vs przepustowość, percentyle końcowe (p95/p99), blokowanie head-of-line, dlaczego `asyncio.gather(*10_000)` jest wolniejszy niż ograniczona pula workerów.
- **Rozmiar puli i prawo Little'a** — `N_workers = przepustowość × latencja`. Dla I/O, rozmiar według pożądanej współbieżności i bandwidth-delay product; dla CPU, według fizycznych rdzeni. Pamiętaj o `ulimit -n` (deskryptory plików) i limitach połączeń kernela.
- **Wzorce backpressure** — ograniczone kolejki (`asyncio.Queue(maxsize=N)`), ograniczanie prędkości token-bucket, circuit breakery (`pybreaker`), timeouty wszędzie jako twarda zasada.
- **Bezpieczeństwo wątków w bibliotekach** — czytaj dokumentację uważnie. Większość sterowników DB: połączenie nie jest thread-safe, kursor jeszcze mniej. `requests.Session` jest prawie-ale-nie-do-końca bezpieczne. Zakres sesji SQLAlchemy. Klienci HTTP z pulami połączeń są zazwyczaj bezpieczni; ORM-y rzadko.
- **Testowanie kodu współbieżnego** — `pytest-asyncio`, `anyio.pytest-plugin`, dlaczego testy współbieżne są niestabilne, testowanie stanowe `hypothesis`, deterministyczne harmonogramy (`trio.testing`).

### Framework i ekosystem

- **ASGI vs WSGI** — różnice cyklu życia, dlaczego FastAPI/Starlette vs Flask/Django-sync, workery gunicorn + uvicorn, async SQLAlchemy, `asyncpg` vs `psycopg3` async.
- **`uvloop`** — zamiennik pętli zdarzeń drop-in, 2–4× szybszy niż pętla selektora stdlib. Domyślny w większości produkcyjnych stosów async.
- **Alternatywne środowiska uruchomieniowe** — `trio` dla nowych projektów które mogą się na to zdecydować, `anyio` dla bibliotek które chcą wspierać oba. Zrozum kiedy stdlib asyncio jest i tak właściwym wyborem (ekosystem).
- **Rozproszona współbieżność** — kiedy jeden węzeł nie wystarczy: `celery`, `dramatiq`, `arq` (async-natywny), `ray` dla ML/obliczeń, `dask` dla danych. Wiedz kiedy przekraczać sieć i kiedy to przerost formy nad treścią.

### Mechanizm CPython i historia

- **Jak działa GIL** — `ceval.c`, `take_gil`/`drop_gil`, interwał przełączania, dlaczego naiwne liczenie referencji sprawiło że GIL był trudny do usunięcia.
- **Mechanizm PEP 703** — tendencyjne liczenie referencji, odroczone RC, nieśmiertelne obiekty (PEP 683), dlaczego specjalizacja jest początkowo wyłączona w wersjach bez GIL-a.
- **PEP 684/734** — GIL per-interpretator, model izolacji pamięci, kanały między-interpretatorowe.
- **Historyczne próby** — Stackless, Gilectomy (Larry Hastings), Jython/IronPython (bez GIL-a z mocy JVM/CLR), PyPy STM. Zrozumienie dlaczego zawiodły wyjaśnia dlaczego PEP 703 jest taki jaki jest.

---

## Dalsza lektura

- [`asyncio`](https://docs.python.org/3/library/asyncio.html) — oficjalna dokumentacja
- [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html) — ujednolicone API wątek/proces
- [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html) — i jego wskazówki programowania
- [PEP 703 — Uczynienie GIL opcjonalnym](https://peps.python.org/pep-0703/)
- [PEP 684 — GIL Per-interpreter](https://peps.python.org/pep-0684/) / [PEP 734 — Wiele interpreterów w stdlib](https://peps.python.org/pep-0734/)
- [`trio`](https://trio.readthedocs.io/) / [`anyio`](https://anyio.readthedocs.io/) — alternatywne / przenośne środowiska uruchomieniowe async (ustrukturyzowana współbieżność jako model podstawowy)
- [`joblib`](https://joblib.readthedocs.io/) — solidny wrapper puli procesów standardowy w stosie data-science
- David Beazley, *Understanding the Python GIL* (nadal najlepszy model myślowy)
