# ENOM

**Finding Earth's planetary analogues through scientific data.**

ENOM is an open-source research prototype for finding Earth environments that share measurable characteristics with locations on the Moon and Mars.

A volcanic landscape in Iceland might resemble part of the lunar surface. A desert on Earth might provide a useful environment for testing a Mars rover. ENOM explores these possibilities by comparing terrain measurements and other scientific observations rather than relying on visual resemblance alone.

The project is being developed for the NASA Space Apps Challenge.

## What ENOM does

ENOM brings planetary and terrestrial observations into one interface, making it easier to investigate possible Earth analogues.

The current prototype lets you:

- Explore indexed locations on Earth, Mars and the Moon.
- Compare planetary terrain with selected Earth environments.
- Rank Earth candidates using measurable terrain characteristics.
- Inspect the measurements behind each result, including missing data and source information.
- Explore Earth–Mars imagery using a separate visual retrieval system.
- Apply experimental terrain-screening criteria for different mission objectives.

**Our next goal** is to let users select any location on the Moon or Mars and automatically discover comparable environments across a much larger Earth dataset.

## How the comparisons work

ENOM's terrain comparisons currently use five measurements:

| Measurement | What it describes |
|---|---|
| Elevation range | Vertical difference across the analysed area |
| Mean slope | Average steepness of the terrain |
| 90th-percentile slope | Steepness across the more inclined parts of the terrain |
| Local relief | Elevation variation within smaller surrounding areas |
| Roughness | Small-scale variation in the terrain surface |

The backend compares measurements with compatible units and spatial scales. It then calculates a weighted similarity score based on the differences between the planetary site and each Earth candidate.

Results also report how much of the requested evidence was available. A high score based on one measurement is not equivalent to a high score supported by all five.

Visual similarity is handled separately using DINOv2 image embeddings. These results help identify imagery worth investigating, but do not establish physical or geological equivalence.

For the calculation, assumptions and limitations, see [NASA Scorecard Methodology](docs/NASA_SCORECARD_METHODOLOGY.md).

## Scientific data

The prototype currently works with a selection of observations from NASA and other scientific providers.

| Source | Use in ENOM |
|---|---|
| Mars Orbiter Laser Altimeter (MOLA) | Martian terrain elevation |
| Lunar Orbiter Laser Altimeter (LOLA) | Lunar terrain elevation |
| Copernicus GLO-30 | Earth terrain measurements |
| Lunar Reconnaissance Orbiter Diviner | Lunar thermal context |
| Mars Global Surveyor TES | Martian thermal inertia context |
| USGS planetary geological maps | Regional geological context |
| Earth and Mars orbital imagery | Visual exploration and retrieval |

Not every dataset is available at every location, and not every observation is used directly in ranking. For example, thermal observations and mapped geological units currently provide additional context rather than matched Earth–planet scoring variables.

See the [Data Source Registry](docs/DATA_SOURCE_REGISTRY.md) for exact products, coverage, resolutions, processing methods and implementation status.

## Current status

ENOM is an experimental research prototype, not a validated analogue discovery service.

The repository currently includes:

- A 100-image Earth–Mars visual retrieval pilot.
- Terrain observations for selected Earth, Moon and Mars locations.
- Missing-data-aware terrain comparison and ranking.
- Experimental landing, rover mobility and base-construction terrain screening.
- A FastAPI backend and React/TypeScript explorer.
- Source provenance, scientific limitations and automated tests.

There are important limitations. Earth candidate coverage is small, some planetary observations are sparse or interpolated, and the rankings have not been independently validated against expert-reviewed analogue pairs.

A suggested analogue should therefore be treated as a **location worth investigating**, not proof of equivalent geology or suitability for a mission.

## Running locally

### Requirements

- Python 3.12+
- Node.js
- [uv](https://docs.astral.sh/uv/)

### Start the backend

From the repository root:

```bash
uv sync --extra dev
uv run uvicorn twinworld.api:app --reload
```

### Start the frontend

In a second terminal:

```bash
cd apps/twinworld
npm ci
npm run dev
```

Open the application at:

`http://127.0.0.1:5173`

FastAPI documentation is available at:

`http://127.0.0.1:8000/api/docs`

### Local datasets

Some large raster files and generated image embeddings are excluded from Git.

A fresh clone can run the application and tests, but indexed visual retrieval requires the corresponding local pilot imagery and embedding artifacts.

The relevant manifests and data preparation instructions are documented in the repository. See [Data Sources](docs/DATA_SOURCES.md) and the [Developer Guide](docs/DEVELOPER_GUIDE.md).

## Development

Run the Python checks:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy src/twinworld
```

Build the frontend:

```bash
cd apps/twinworld
npm ci
npm run build
```

The source is organised into three main areas:

| Directory | Purpose |
|---|---|
| `src/twinworld/` | Scientific processing, comparison logic and API |
| `apps/twinworld/` | Browser application |
| `scripts/` | Data ingestion, preparation and evaluation |

For an explanation of how the code fits together, see [Architecture](docs/ARCHITECTURE.md).

## Where we're heading

The next major development goal is **autonomous Earth analogue discovery**.

Instead of selecting only from existing planetary sites, a user should eventually be able to click a point on the Moon or Mars and have ENOM:

1. Retrieve available scientific observations for that location.
2. Calculate comparable environmental measurements.
3. Search an expanded index of Earth environments.
4. Rank and explain the strongest supported matches.
5. Show those results directly on the Earth globe.

Achieving this will require broader Earth coverage, reliable processing of arbitrary planetary coordinates, and careful validation of the comparison methodology.

## Further reading

- [System Architecture](docs/ARCHITECTURE.md)
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [Scientific Architecture](docs/SCIENTIFIC_ARCHITECTURE.md)
- [Data Source Registry](docs/DATA_SOURCE_REGISTRY.md)
- [NASA Scorecard Methodology](docs/NASA_SCORECARD_METHODOLOGY.md)
- [NASA Challenge Alignment](docs/NASA_CHALLENGE_ALIGNMENT.md)
