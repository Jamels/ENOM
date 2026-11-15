"""Place-level, evidence-aware analogue discovery over the checked-in catalogue.

Places are the ranking unit. Image patches and source products are observations linked
to a place; they never become separate ranked places just because they are separate
files. Compatible terrain measurements and a separate terrain-derived operations proxy
can contribute to numeric similarity; mission suitability is not assessed here.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

from twinworld.dimension_scoring import compare_dimensions
from twinworld.records import PatchRecord, read_jsonl

DIMENSIONS: dict[str, dict[str, str]] = {
    "geology_materials": {
        "label": "Geology, minerals & materials",
        "unit": "mapped or measured material evidence",
    },
    "terrain": {"label": "Terrain & surface hazards", "unit": "m, degrees; scale-dependent"},
    "thermal_illumination": {
        "label": "Temperature & illumination",
        "unit": "K; illumination not yet measured",
    },
    "water_resources": {"label": "Water, ice & resources", "unit": "source-specific"},
    "dust_processes": {"label": "Dust, wind & erosion", "unit": "source-specific"},
    "biology_habitability": {
        "label": "Biology & habitability",
        "unit": "documented Earth studies only",
    },
    "subsurface": {"label": "Caves & subsurface", "unit": "interpreted; confidence varies"},
    "mission_operations": {
        "label": "Mission operations",
        "unit": "terrain-derived proxy; vehicle limits separate",
    },
}

PROFILES: dict[str, dict[str, Any]] = {
    "dunes": {
        "name": "Dunes & wind processes",
        "description": "Compare dune terrain and surface processes.",
        "weights": {
            "geology_materials": 0.15,
            "terrain": 0.25,
            "thermal_illumination": 0.05,
            "water_resources": 0.05,
            "dust_processes": 0.35,
            "biology_habitability": 0.02,
            "subsurface": 0.03,
            "mission_operations": 0.10,
        },
    },
    "polar_resources": {
        "name": "Polar resources",
        "description": "Compare cold, illumination and possible resource settings.",
        "weights": {
            "geology_materials": 0.10,
            "terrain": 0.15,
            "thermal_illumination": 0.20,
            "water_resources": 0.35,
            "dust_processes": 0.03,
            "biology_habitability": 0.02,
            "subsurface": 0.05,
            "mission_operations": 0.10,
        },
    },
    "geology_materials": {
        "name": "Geology & materials",
        "description": "Compare mapped geology and material evidence.",
        "weights": {
            "geology_materials": 0.55,
            "terrain": 0.10,
            "thermal_illumination": 0.03,
            "water_resources": 0.05,
            "dust_processes": 0.05,
            "biology_habitability": 0.02,
            "subsurface": 0.10,
            "mission_operations": 0.10,
        },
    },
    "subsurface_targets": {
        "name": "Caves & subsurface targets",
        "description": "Compare surface clues and confirmed subsurface evidence separately.",
        "weights": {
            "geology_materials": 0.10,
            "terrain": 0.10,
            "thermal_illumination": 0.03,
            "water_resources": 0.10,
            "dust_processes": 0.02,
            "biology_habitability": 0.02,
            "subsurface": 0.53,
            "mission_operations": 0.18,
        },
    },
    "mission_operations": {
        "name": "Mission operations",
        "description": (
            "Compare terrain evidence relevant to landing, mobility and field operations."
        ),
        "weights": {
            "geology_materials": 0.05,
            "terrain": 0.45,
            "thermal_illumination": 0.08,
            "water_resources": 0.08,
            "dust_processes": 0.08,
            "biology_habitability": 0.01,
            "subsurface": 0.05,
            "mission_operations": 0.28,
        },
    },
}
MIN_MOLA_OBSERVED_FRACTION = float(os.getenv("TWINWORLD_MIN_TERRAIN_COVERAGE", "0.25"))
OPERATIONS_PROXY_VARIABLES = {
    "mean_slope",
    "slope_p90",
    "median_local_relief_3x3",
    "median_roughness_3x3",
}

SOURCE_GUIDES: dict[str, list[dict[str, str]]] = {
    "geology_materials": [
        {"name": "USGS mapped geology", "url": "https://astrogeology.usgs.gov/"},
        {"name": "NASA CRISM (Mars) / M³ (Moon)", "url": "https://pds-geosciences.wustl.edu/"},
        {
            "name": "USGS Spectral Library (reference spectra)",
            "url": "https://www.usgs.gov/labs/spectroscopy-lab/science/spectral-library",
        },
    ],
    "terrain": [
        {
            "name": "Copernicus DEM GLO-30",
            "url": "https://planetarycomputer.microsoft.com/dataset/copernicus-dem",
        },
        {"name": "MOLA MEGDR / LOLA LDEM", "url": "https://pds-geosciences.wustl.edu/"},
    ],
    "thermal_illumination": [
        {
            "name": "NASA LRO Diviner",
            "url": "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm",
        },
        {"name": "Mars TES / THEMIS", "url": "https://pds-geosciences.wustl.edu/"},
        {"name": "NASA POWER Earth climate", "url": "https://power.larc.nasa.gov/"},
        {
            "name": "ECMWF ERA5 historical reanalysis",
            "url": "https://open-meteo.com/en/docs/historical-weather-api",
        },
        {
            "name": "Mars 2020 MEDA environmental archive",
            "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
        },
    ],
    "water_resources": [
        {
            "name": "NASA LEND neutron measurements (Moon)",
            "url": "https://pds-geosciences.wustl.edu/missions/lro/lend.htm",
        },
        {
            "name": "NASA Mini-RF CPR mosaic (Moon)",
            "url": "https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/lromrf_0005/data/sar/mosaics/lsz_xxxxx_3cp_pfu_90s000_v1.lbl",
        },
        {"name": "SHARAD / CRISM (Mars)", "url": "https://pds-geosciences.wustl.edu/"},
        {"name": "NSIDC snow and permafrost (Earth)", "url": "https://nsidc.org/data"},
        {
            "name": "NASA POWER 2 m relative humidity (Earth context)",
            "url": "https://power.larc.nasa.gov/docs/methodology/data/derived/met-derived-parameters/",
        },
        {
            "name": "Mars 2020 MEDA near-surface relative humidity",
            "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
        },
    ],
    "dust_processes": [
        {"name": "Mars rover environmental records", "url": "https://pds.nasa.gov/"},
        {"name": "Repeat CTX / HiRISE observations", "url": "https://ode.rsl.wustl.edu/mars/"},
        {"name": "NASA POWER Earth wind climatology", "url": "https://power.larc.nasa.gov/"},
        {
            "name": "ECMWF ERA5 historical 10 m wind",
            "url": "https://open-meteo.com/en/docs/historical-weather-api",
        },
        {
            "name": "Mars 2020 MEDA rover wind sensor",
            "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
        },
    ],
    "biology_habitability": [
        {"name": "Documented Earth extremophile studies", "url": "https://astrobiology.nasa.gov/"},
    ],
    "subsurface": [
        {
            "name": "LROC / LOLA (Moon); CTX / HiRISE / radar (Mars)",
            "url": "https://ode.rsl.wustl.edu/",
        },
        {
            "name": "Earth cave survey records",
            "url": "https://www.nps.gov/subjects/caves/index.htm",
        },
    ],
    "mission_operations": [
        {"name": "NASA Planetary Data System rover archives", "url": "https://pds.nasa.gov/"},
    ],
}

SOURCE_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "usgs-mars-geology",
        "name": "USGS SIM 1083 Mars geology",
        "dimension": "geology_materials",
        "bodies": ["mars"],
        "dataset_id": "usgs-sim-1083-mars-global-geology",
        "provider": "USGS Astrogeology",
        "status": "operational",
        "role": "Regional mapped interpretation; not a local assay.",
        "url": "https://doi.org/10.5066/P9UGAC18",
    },
    {
        "id": "usgs-lunar-geology",
        "name": "USGS Unified Geologic Map of the Moon",
        "dimension": "geology_materials",
        "bodies": ["moon"],
        "dataset_id": "usgs-fortezzo-2020-unified-lunar-geology",
        "provider": "USGS Astrogeology",
        "status": "operational",
        "role": "Regional mapped interpretation; not a local assay.",
        "url": "https://astrogeology.usgs.gov/search/map/Moon/Geology/Unified_Geologic_Map_of_the_Moon_GIS_v2/",
    },
    {
        "id": "crism",
        "name": "MRO CRISM hyperspectral observations",
        "dimension": "geology_materials",
        "bodies": ["mars"],
        "provider": "NASA PDS",
        "status": "not_connected",
        "role": "Mineral spectral observations; no candidate-site product is indexed yet.",
        "url": "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-v1/mrocr_2xxx/",
    },
    {
        "id": "m3",
        "name": "Chandrayaan-1 Moon Mineralogy Mapper (M³)",
        "dimension": "geology_materials",
        "bodies": ["moon"],
        "provider": "ISRO / NASA PDS",
        "status": "not_connected",
        "role": "Lunar spectral mineralogy; no candidate-site product is indexed yet.",
        "url": "https://pds-imaging.jpl.nasa.gov/volumes/m3.html",
    },
    {
        "id": "usgs-spectral-library",
        "name": "USGS Spectral Library",
        "dimension": "geology_materials",
        "bodies": ["earth", "mars", "moon"],
        "provider": "USGS",
        "status": "reference_only",
        "role": "Reference spectra; does not provide a measurement at a candidate place.",
        "url": "https://www.usgs.gov/labs/spectroscopy-lab/science/spectral-library",
    },
    {
        "id": "usgs-earth-geology",
        "name": "USGS State Geologic Map Compilation",
        "dimension": "geology_materials",
        "bodies": ["earth"],
        "dataset_id": "usgs-earth-sgmc",
        "provider": "USGS / State Geological Surveys",
        "status": "operational",
        "role": (
            "Point-query map context for candidate places in the "
            "conterminous U.S.; compiled state units and scales vary, and "
            "places outside the map extent are explicit gaps."
        ),
        "url": "https://doi.org/10.5066/F7WH2N65",
    },
    {
        "id": "cop-dem-glo-30",
        "name": "Copernicus DEM GLO-30",
        "dimension": "terrain",
        "bodies": ["earth"],
        "dataset_id": "cop-dem-glo-30",
        "provider": "Copernicus / Microsoft Planetary Computer",
        "status": "operational",
        "role": (
            "Ten pilot and eight candidate-place contexts; nodata coverage retained per window."
        ),
        "url": "https://planetarycomputer.microsoft.com/dataset/copernicus-dem",
    },
    {
        "id": "mola-meg128",
        "name": "MGS MOLA MEGDR",
        "dimension": "terrain",
        "bodies": ["mars"],
        "dataset_id": "mola-meg128",
        "provider": "NASA PDS",
        "status": "operational",
        "role": "Ten pilot and three candidate contexts; sparse bins are masked from measurements.",
        "url": "https://pds-geosciences.wustl.edu/missions/mgs/megdr.html",
    },
    {
        "id": "lola-ldem64",
        "name": "LRO LOLA LDEM_64 cylindrical product",
        "dimension": "terrain",
        "bodies": ["moon"],
        "dataset_id": "lro-lola-gdr-ldem-64",
        "provider": "NASA PDS",
        "status": "operational",
        "role": (
            "Four low-latitude scorecard/candidate contexts; south-polar "
            "candidate terrain still needs a polar product."
        ),
        "url": "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/",
    },
    {
        "id": "lola-polar-dem",
        "name": "LOLA 75S polar DEM and direct-shot counts",
        "dimension": "terrain",
        "bodies": ["moon"],
        "dataset_id": "lro-lola-gdr-polar-ldem-120m",
        "provider": "NASA PDS Geosciences Node",
        "status": "operational",
        "role": (
            "Bounded LDEM_75S_120M and paired LDEC direct-shot crops at "
            "Shackleton, Malapert, and de Gerlache; unsupported native cells "
            "are masked."
        ),
        "url": "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_120m.lbl",
    },
    {
        "id": "nasadem",
        "name": "NASADEM HGT",
        "dimension": "terrain",
        "bodies": ["earth"],
        "dataset_id": "nasadem-hgt",
        "provider": "NASA LP DAAC",
        "status": "registered",
        "role": "Adapter exists; no candidate-site product is currently indexed.",
        "url": "https://doi.org/10.5067/MEASURES/NASADEM/NASADEM_HGT.001",
    },
    {
        "id": "hirise-dem",
        "name": "HiRISE stereo terrain products",
        "dimension": "terrain",
        "bodies": ["mars"],
        "provider": "NASA PDS",
        "status": "not_connected",
        "role": "High-resolution local terrain; no candidate-site DEM is indexed.",
        "url": "https://ode.rsl.wustl.edu/mars/",
    },
    {
        "id": "diviner",
        "name": "LRO Diviner surface temperature",
        "dimension": "thermal_illumination",
        "bodies": ["moon"],
        "dataset_id": "lro-diviner-gdr-level3-st-clc",
        "provider": "NASA PDS",
        "status": "operational",
        "role": (
            "Bounded nighttime regolith-temperature windows at "
            "candidate/demo sites; no Earth pairing or illumination model."
        ),
        "url": "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm",
    },
    {
        "id": "diviner-prp",
        "name": "LRO Diviner south-polar resource product",
        "dimension": "thermal_illumination",
        "bodies": ["moon"],
        "dataset_id": "lro-diviner-prp-south-polar",
        "provider": "NASA PDS Geosciences Node",
        "status": "operational",
        "role": (
            "Nearest-triangle annual temperature and modeled "
            "ice-stability-depth samples at three lunar south-polar "
            "candidates; first-mapping-year model context, not direct ice "
            "detection or cross-body scoring."
        ),
        "url": "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/dlre_prp_south.lbl",
    },
    {
        "id": "tes",
        "name": "Mars Global Surveyor TES thermal inertia",
        "dimension": "thermal_illumination",
        "bodies": ["mars"],
        "dataset_id": "mgs-tes-derived-thermal-inertia",
        "provider": "NASA PDS",
        "status": "operational",
        "role": (
            "Bounded derived Mars thermal-inertia windows at candidate/demo "
            "sites; this quantity is not temperature."
        ),
        "url": "https://pds-geosciences.wustl.edu/mgs/tes-timap.html",
    },
    {
        "id": "earth-modis",
        "name": "NASA MODIS land-surface temperature",
        "dimension": "thermal_illumination",
        "bodies": ["earth"],
        "provider": "NASA LP DAAC",
        "status": "not_connected",
        "role": "No candidate-site time series is indexed.",
        "url": "https://lpdaac.usgs.gov/products/mod11a2v061/",
    },
    {
        "id": "era5-temperature",
        "name": "ERA5 Earth 2 m air-temperature climatology",
        "dimension": "thermal_illumination",
        "bodies": ["earth"],
        "dataset_id": "era5-earth-candidate-climatology",
        "measurement_names": ["ERA5 monthly mean 2 m air temperature"],
        "provider": "ECMWF/Copernicus via Open-Meteo",
        "status": "operational",
        "role": (
            "1991–2020 daily reanalysis summarized by month at the nearest "
            "0.25° grid point; Earth air temperature context only, not "
            "lunar/Martian surface temperature."
        ),
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
    },
    {
        "id": "solar-illumination-model",
        "name": "Terrain and solar-position illumination estimate",
        "dimension": "thermal_illumination",
        "bodies": ["earth", "mars", "moon"],
        "provider": "Derived from source terrain and ephemerides",
        "status": "not_connected",
        "role": "No illumination or shadow calculation is indexed.",
        "url": "https://naif.jpl.nasa.gov/naif/",
    },
    {
        "id": "nasa-power-thermal",
        "name": "NASA POWER climatology: temperature and solar radiation",
        "dimension": "thermal_illumination",
        "bodies": ["earth"],
        "dataset_id": "nasa-power-climatology",
        "provider": "NASA Langley POWER",
        "status": "operational",
        "role": (
            "Point climatology at eight Earth catalogue locations; "
            "model/reanalysis context, not local sensor data."
        ),
        "url": "https://power.larc.nasa.gov/docs/services/api/temporal/climatology/",
    },
    {
        "id": "lunar-lend",
        "name": "LRO LEND averaged south-polar neutron counts",
        "dimension": "water_resources",
        "bodies": ["moon"],
        "dataset_id": "lro-lend-south-polar-alds",
        "provider": "NASA PDS Geosciences Node",
        "status": "operational",
        "role": (
            "CSETN count-rate records from two multi-year ALDS periods "
            "through 2016 at Shackleton, Malapert, and de Gerlache; later "
            "RDR_DLD records are not indexed. Indirect hydrogen context "
            "only, not water or usable-resource confirmation."
        ),
        "url": "https://pds-geosciences.wustl.edu/missions/lro/lend.htm",
    },
    {
        "id": "mini-rf-cpr",
        "name": "LRO Mini-RF south-polar circular polarization ratio mosaic",
        "dimension": "water_resources",
        "bodies": ["moon"],
        "dataset_id": "lro-mini-rf-south-polar-cpr",
        "provider": "NASA PDS Geosciences Node",
        "status": "operational",
        "role": (
            "5×5-pixel CPR context samples at Shackleton, Malapert, and de "
            "Gerlache; CPR is not a unique ice signal and is not scored."
        ),
        "url": "https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/lromrf_0005/data/sar/mosaics/lsz_xxxxx_3cp_pfu_90s000_v1.lbl",
    },
    {
        "id": "mars-sharad-crism",
        "name": "SHARAD and CRISM volatile indicators",
        "dimension": "water_resources",
        "bodies": ["mars"],
        "provider": "NASA PDS",
        "status": "not_connected",
        "role": "No candidate-site radar or spectral evidence is indexed.",
        "url": "https://pds-geosciences.wustl.edu/",
    },
    {
        "id": "nsidc",
        "name": "NSIDC snow and permafrost products",
        "dimension": "water_resources",
        "bodies": ["earth"],
        "provider": "NSIDC",
        "status": "not_connected",
        "role": "No candidate-site resource layer is indexed.",
        "url": "https://nsidc.org/data",
    },
    {
        "id": "era5-wind",
        "name": "ERA5 Earth 10 m wind climatology",
        "dimension": "dust_processes",
        "bodies": ["earth"],
        "dataset_id": "era5-earth-candidate-climatology",
        "measurement_names": ["ERA5 monthly mean 10 m wind speed"],
        "provider": "ECMWF/Copernicus via Open-Meteo",
        "status": "operational",
        "role": (
            "1991–2020 daily reanalysis summaries; weather context only, not "
            "a dust event, erosion rate, or local sensor record."
        ),
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
    },
    {
        "id": "nasa-power-wind",
        "name": "NASA POWER 10 m wind climatology",
        "dimension": "dust_processes",
        "bodies": ["earth"],
        "dataset_id": "nasa-power-climatology",
        "provider": "NASA Langley POWER",
        "status": "operational",
        "role": (
            "Gridded annual/monthly wind climatology at eight Earth "
            "catalogue locations; not local wind observations or dust "
            "activity."
        ),
        "url": "https://power.larc.nasa.gov/docs/services/api/temporal/climatology/",
    },
    {
        "id": "nasa-power-humidity",
        "name": "NASA POWER 2 m relative humidity climatology",
        "dimension": "water_resources",
        "bodies": ["earth"],
        "dataset_id": "nasa-power-climatology",
        "provider": "NASA Langley POWER / MERRA-2",
        "status": "operational",
        "role": (
            "Gridded near-surface atmospheric humidity context at the eight "
            "Earth catalogue points; it does not measure liquid water, "
            "ground ice, or an extractable resource."
        ),
        "url": "https://power.larc.nasa.gov/docs/methodology/data/derived/met-derived-parameters/",
    },
    {
        "id": "mars2020-meda-temperature",
        "name": "Mars 2020 MEDA local air temperature",
        "dimension": "thermal_illumination",
        "bodies": ["mars"],
        "dataset_id": "mars2020-meda",
        "measurement_names": ["MEDA ATS local air temperature near mast sensor 1"],
        "provider": "NASA PDS Atmospheres Node",
        "status": "operational",
        "role": (
            "Calibrated near-surface air temperature summary for one "
            "Perseverance sol at Jezero; context only, not a seasonal "
            "climate statistic or Earth comparison."
        ),
        "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
    },
    {
        "id": "mars2020-meda-wind",
        "name": "Mars 2020 MEDA horizontal wind",
        "dimension": "dust_processes",
        "bodies": ["mars"],
        "dataset_id": "mars2020-meda",
        "measurement_names": ["MEDA horizontal wind speed"],
        "provider": "NASA PDS Atmospheres Node",
        "status": "operational",
        "role": (
            "Derived rover wind samples for one sol at Jezero, filtered to "
            "stationary-rover rows; not a long-term climate or dust-activity "
            "measure."
        ),
        "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
    },
    {
        "id": "mars2020-meda-humidity",
        "name": "Mars 2020 MEDA near-surface relative humidity",
        "dimension": "water_resources",
        "bodies": ["mars"],
        "dataset_id": "mars2020-meda",
        "measurement_names": ["MEDA near-surface atmospheric relative humidity"],
        "provider": "NASA PDS Atmospheres Node",
        "status": "operational",
        "role": (
            "Derived atmospheric relative humidity summary for one sol at "
            "Jezero; not soil water, ground ice, or a usable resource."
        ),
        "url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
    },
    {
        "id": "era5-precipitation",
        "name": "ERA5 Earth precipitation climatology",
        "dimension": "water_resources",
        "bodies": ["earth"],
        "dataset_id": "era5-earth-candidate-climatology",
        "measurement_names": ["ERA5 average monthly precipitation total"],
        "provider": "ECMWF/Copernicus via Open-Meteo",
        "status": "operational",
        "role": (
            "Grid-based monthly precipitation context; does not measure soil "
            "moisture, groundwater, permafrost, or available resources."
        ),
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
    },
    {
        "id": "mars2020-rover-places",
        "name": "Perseverance PLACES best-tactical drive localizations",
        "dimension": "mission_operations",
        "bodies": ["mars"],
        "dataset_id": "mars2020-rover-places-best-tactical",
        "provider": "NASA PDS Geosciences Node",
        "status": "operational",
        "role": (
            "Discrete localized rover positions in the Jezero candidate "
            "region through sol 1896; position fixes are not continuous "
            "wheel tracks, vehicle-performance limits, or a safety "
            "assessment."
        ),
        "url": "https://pds-geosciences.wustl.edu/missions/mars2020/places.htm",
    },
    {
        "id": "mars-repeat-imagery-weather",
        "name": "Mars rover weather and repeat CTX/HiRISE",
        "dimension": "dust_processes",
        "bodies": ["mars"],
        "provider": "NASA PDS",
        "status": "not_connected",
        "role": "No repeated-observation change detection or rover weather series is indexed.",
        "url": "https://ode.rsl.wustl.edu/mars/",
    },
    {
        "id": "earth-extremophile-studies",
        "name": "Earth extremophile field studies",
        "dimension": "biology_habitability",
        "bodies": ["earth"],
        "dataset_id": "earth-extremophile-studies",
        "provider": "Peer-reviewed field research",
        "status": "context_only",
        "role": (
            "Study-linked Earth biology and habitability context at Yungay, "
            "Haughton, and McMurdo; spatial precision varies and evidence is "
            "not scored."
        ),
        "url": "https://doi.org/10.1038/s41598-020-76302-z",
    },
    {
        "id": "candidate-subsurface-context",
        "name": "Catalogue cave and pit source records",
        "dimension": "subsurface",
        "bodies": ["earth", "moon"],
        "dataset_id": "candidate-subsurface-context",
        "provider": "National Park Service / peer-reviewed lunar studies",
        "status": "context_only",
        "role": (
            "Five source-linked candidate descriptions: three named Earth "
            "cave locations and two lunar pits. The lunar cave connections "
            "are hypotheses; no surveyed subsurface geometry is indexed."
        ),
        "url": "https://www.nps.gov/subjects/caves/index.htm",
    },
    {
        "id": "cave-records",
        "name": "Earth cave survey geometry",
        "dimension": "subsurface",
        "bodies": ["earth"],
        "provider": "National Park Service / USGS",
        "status": "not_connected",
        "role": (
            "No cave survey geometry or entrance-to-chamber measurements are "
            "linked to ENOM candidate places."
        ),
        "url": "https://www.nps.gov/subjects/caves/index.htm",
    },
    {
        "id": "candidate-mission-site-context",
        "name": "Catalogue planetary mission-site records",
        "dimension": "mission_operations",
        "bodies": ["mars"],
        "dataset_id": "candidate-mission-site-context",
        "provider": "NASA / USGS mission-site references",
        "status": "context_only",
        "role": (
            "Three Mars landing-site descriptions are linked as context; "
            "they do not contain rover traverses, operations timelines, or "
            "vehicle performance data."
        ),
        "url": "https://pds.nasa.gov/",
    },
    {
        "id": "mission-operations",
        "name": "Rover and lander operation records",
        "dimension": "mission_operations",
        "bodies": ["mars", "moon"],
        "provider": "NASA PDS",
        "status": "not_connected",
        "role": (
            "No operational timeline or vehicle-specific constraint model is "
            "joined to candidate places."
        ),
        "url": "https://pds.nasa.gov/",
    },
]


def validate_dimension_weights(weights: dict[str, float]) -> dict[str, float]:
    if set(weights) != set(DIMENSIONS):
        missing, extra = set(DIMENSIONS) - set(weights), set(weights) - set(DIMENSIONS)
        raise ValueError(
            f"Weights must include all eight dimensions (missing={sorted(missing)}, "
            f"unknown={sorted(extra)})"
        )
    checked: dict[str, float] = {}
    for key, value in weights.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"Weight '{key}' must be a finite, non-negative number")
        checked[key] = float(value)
    try:
        total = math.fsum(checked.values())
    except OverflowError as exc:
        raise ValueError("The total dimension weight must be finite") from exc
    if not math.isfinite(total):
        raise ValueError("The total dimension weight must be finite")
    if total <= 0:
        raise ValueError("At least one dimension weight must be greater than zero")
    return checked


def _normal_group(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def build_places(
    root: Path, *, include_unreviewed: bool = False, include_archived: bool = False
) -> list[dict[str, Any]]:
    """Create place records from the scientific catalogue and observation manifests."""
    catalogue_path = root / "data/manifests/candidate-locations.json"
    catalogue = (
        json.loads(catalogue_path.read_text()) if catalogue_path.is_file() else {"entries": []}
    )
    places: dict[str, dict[str, Any]] = {}
    for entry in catalogue.get("entries", []):
        if entry.get("status") == "archived" and not include_archived:
            continue
        place_id = str(entry["id"])
        places[place_id] = {
            "id": place_id,
            "name": entry["name"],
            "body": entry["body"],
            "longitude_east_deg": entry["longitude_east_deg"],
            "latitude_deg": entry["latitude_deg"],
            "status": entry.get("status", "candidate"),
            "default_visible": True,
            "basis": entry.get("basis"),
            "source_url": entry.get("source_url"),
            "observations": [],
            "candidate_type": entry.get("candidate_type"),
        }

    records = (
        read_jsonl(root / "data/manifests/pilot-100.jsonl")
        if (root / "data/manifests/pilot-100.jsonl").is_file()
        else []
    )
    grouped: dict[str, list[PatchRecord]] = defaultdict(list)
    for record in records:
        if record.body == "earth":
            grouped[record.geographic_group].append(record)
    for group, rows in grouped.items():
        visible_rows = (
            rows if include_unreviewed else [row for row in rows if row.label_status == "verified"]
        )
        if not visible_rows:
            continue
        place_id = "earth-pilot-" + _normal_group(group.removeprefix("earth_"))
        lat = median(row.latitude for row in visible_rows)
        lon = median(row.longitude for row in visible_rows)
        places[place_id] = {
            "id": place_id,
            "name": visible_rows[0].processing.get("site_name", group.replace("_", " ")),
            "body": "earth",
            "longitude_east_deg": lon % 360,
            "latitude_deg": lat,
            "status": "pilot_region",
            "default_visible": True,
            "basis": (
                "Earth image-patch group from the pilot manifest; morphology "
                "label review status is shown per observation."
            ),
            "source_url": visible_rows[0].source_url,
            "observations": [],
            "candidate_type": "pilot_observation_group",
        }

    for path in sorted((root / "data/terrain").glob("*.tif.json")):
        try:
            metadata = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        observation_id = metadata.get("observation_id")
        if not observation_id:
            continue
        patch = next((record for record in records if record.image_id == observation_id), None)
        if patch and patch.body == "earth":
            target_group = patch.geographic_group
            place = next(
                (
                    p
                    for p in places.values()
                    if p["id"]
                    == "earth-pilot-" + _normal_group(target_group.removeprefix("earth_"))
                ),
                None,
            )
            if place is None:
                # Known catalogue places without reviewed pilot labels are still valid candidates.
                place = next(
                    (
                        p
                        for p in places.values()
                        if p["body"] == "earth"
                        and _distance_km(
                            p["latitude_deg"],
                            p["longitude_east_deg"],
                            patch.latitude,
                            patch.longitude,
                        )
                        < 15
                    ),
                    None,
                )
        else:
            body = metadata.get("body")
            lat, lon = metadata.get("latitude_deg"), metadata.get("longitude_east_deg")
            place = places.get(str(metadata.get("place_id"))) if metadata.get("place_id") else None
            if place is None:
                place = next(
                    (
                        p
                        for p in places.values()
                        if p["body"] == body
                        and isinstance(lat, (int, float))
                        and isinstance(lon, (int, float))
                        and _distance_km(
                            p["latitude_deg"], p["longitude_east_deg"], lat, lon, str(body)
                        )
                        < 5
                    ),
                    None,
                )
            if place is None:
                place = next(
                    (
                        p
                        for p in places.values()
                        if p["body"] == body
                        and p.get("status") == "observed_context"
                        and _distance_km(
                            p["latitude_deg"], p["longitude_east_deg"], lat, lon, str(body)
                        )
                        < 5
                    ),
                    None,
                )
            if (
                place is None
                and body in {"moon", "mars"}
                and isinstance(lat, (int, float))
                and isinstance(lon, (int, float))
            ):
                place_id = "observed-" + _normal_group(str(observation_id))
                place_name = metadata.get("name", str(observation_id))
                place = places.setdefault(
                    place_id,
                    {
                        "id": place_id,
                        "name": place_name,
                        "body": body,
                        "longitude_east_deg": lon % 360,
                        "latitude_deg": lat,
                        "status": "observed_context",
                        "default_visible": True,
                        "basis": (
                            "A source-backed observation context; footprint may not be a "
                            "named landing site."
                        ),
                        "source_url": metadata.get("source_url"),
                        "observations": [],
                        "candidate_type": "observed_context",
                    },
                )
        if place is not None:
            measurement_rows = metadata.get("measurements", [])
            if not measurement_rows and isinstance(metadata.get("measurement"), dict):
                measurement_rows = [metadata["measurement"]]
            place["observations"].append(
                {
                    "id": observation_id,
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("source_product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("observation_period"),
                    "kind": "measurement"
                    if metadata.get("measurements")
                    else "environmental_evidence",
                    "measurements": measurement_rows,
                    "metadata": metadata,
                }
            )

    for path in sorted((root / "data/geology").glob("*.json")):
        try:
            metadata = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        observation_id = metadata.get("observation_id")
        place = next(
            (
                p
                for p in places.values()
                if p["id"] == observation_id
                or any(o["id"] == observation_id for o in p["observations"])
            ),
            None,
        )
        if place is None:
            continue
        place["observations"].append(
            {
                "id": observation_id,
                "dataset_id": metadata.get("dataset_id"),
                "product_id": metadata.get("source_product_id"),
                "source_url": metadata.get("dataset_reference_url") or metadata.get("source_url"),
                "provider": metadata.get("provider"),
                "acquired_at": metadata.get("retrieved_at"),
                "kind": "geologic_interpretation",
                "classification_status": metadata.get("classification_status"),
                "map_unit_code": metadata.get("map_unit_code"),
                "map_unit_name": metadata.get("map_unit_name"),
                "map_unit_interpretation": metadata.get("map_unit_interpretation"),
                "measurements": [],
                "metadata": metadata,
            }
        )

    power_path = root / "data/environment/nasa-power-climatology.json"
    if power_path.is_file():
        try:
            power_records = json.loads(power_path.read_text()).get("records", [])
        except (OSError, json.JSONDecodeError):
            power_records = []
        for metadata in power_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["place_id"]) + ":nasa-power-climatology",
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("source_product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("retrieved_at"),
                    "kind": "climatology",
                    "measurements": metadata.get("measurements", []),
                    "metadata": metadata,
                }
            )

    era5_path = root / "data/environment/era5-earth-candidate-climatology.json"
    if era5_path.is_file():
        try:
            era5_records = json.loads(era5_path.read_text(encoding="utf-8")).get("records", [])
        except (OSError, json.JSONDecodeError):
            era5_records = []
        for metadata in era5_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("observation_period"),
                    "kind": "climatology",
                    "measurements": metadata.get("measurements", []),
                    "metadata": metadata,
                }
            )

    meda_path = root / "data/environment/mars2020-meda-sol100.json"
    if meda_path.is_file():
        try:
            meda_records = json.loads(meda_path.read_text(encoding="utf-8")).get("records", [])
        except (OSError, json.JSONDecodeError):
            meda_records = []
        for metadata in meda_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("acquired_at"),
                    "kind": "measurement",
                    "measurements": metadata.get("measurements", []),
                    "metadata": metadata,
                }
            )

    rover_places_path = root / "data/environment/mars2020-jezero-rover-places.json"
    if rover_places_path.is_file():
        try:
            rover_payload = json.loads(rover_places_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rover_payload = {}
        place = places.get(str(rover_payload.get("place_id")))
        points = rover_payload.get("records", [])
        if place is not None and points:
            place["observations"].append(
                {
                    "id": f"{place['id']}:{rover_payload.get('dataset_id')}",
                    "dataset_id": rover_payload.get("dataset_id"),
                    "product_id": rover_payload.get("product_id"),
                    "source_url": rover_payload.get("source_url"),
                    "provider": rover_payload.get("provider"),
                    "acquired_at": f"Mars sols {min(row['sol'] for row in points)}–"
                    f"{max(row['sol'] for row in points)}",
                    "kind": "mission_operations_context",
                    "measurements": [
                        {
                            "name": "Localized Perseverance drive-position fixes",
                            "value": len(points),
                            "units": "positions",
                            "availability": "available",
                            "sample_count": len(points),
                            "summary_statistic": (
                                "Discrete best-tactical localization rows within the candidate "
                                "region; not a continuous traverse path"
                            ),
                        }
                    ],
                    "metadata": {
                        **rover_payload,
                        "summary": (
                            f"{len(points)} selected Perseverance drive-position fixes in a "
                            f"{rover_payload.get('candidate_region_radius_km')} km radius; "
                            f"Mars sols {min(row['sol'] for row in points)}–"
                            f"{max(row['sol'] for row in points)}."
                        ),
                        "sample_count": len(points),
                        "uncertainty": rover_payload.get("position_uncertainty"),
                        "context_size_m": float(
                            rover_payload.get("candidate_region_radius_km", 20.0)
                        )
                        * 2000,
                        "latitude_deg": place.get("latitude_deg"),
                        "longitude_east_deg": place.get("longitude_east_deg"),
                    },
                }
            )

    minirf_path = root / "data/environment/lro-mini-rf-south-polar-cpr.json"
    if minirf_path.is_file():
        try:
            minirf_records = json.loads(minirf_path.read_text(encoding="utf-8")).get("records", [])
        except (OSError, json.JSONDecodeError):
            minirf_records = []
        for metadata in minirf_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("temporal_coverage"),
                    "kind": "measurement",
                    "measurements": [
                        {
                            "name": metadata.get("measurement_name"),
                            "value": metadata.get("value"),
                            "units": metadata.get("units"),
                            "spatial_scale_m": metadata.get("spatial_scale_m"),
                            "sample_count": metadata.get("spatial_coverage", {}).get(
                                "valid_pixel_count"
                            ),
                            "availability": "available",
                            "uncertainty": metadata.get("uncertainty"),
                        }
                    ],
                    "metadata": metadata,
                }
            )

    lend_path = root / "data/environment/lro-lend-south-polar-alds.json"
    if lend_path.is_file():
        try:
            lend_records = json.loads(lend_path.read_text(encoding="utf-8")).get("records", [])
        except (OSError, json.JSONDecodeError):
            lend_records = []
        for metadata in lend_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("observation_period"),
                    "kind": "measurement",
                    "measurements": [metadata.get("measurement", {})],
                    "metadata": metadata,
                }
            )

    diviner_prp_path = root / "data/environment/lro-diviner-south-polar-prp.json"
    if diviner_prp_path.is_file():
        try:
            diviner_prp_records = json.loads(diviner_prp_path.read_text(encoding="utf-8")).get(
                "records", []
            )
        except (OSError, json.JSONDecodeError):
            diviner_prp_records = []
        for metadata in diviner_prp_records:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("observation_period"),
                    "kind": "model_derived_measurement",
                    "measurements": metadata.get("measurements", []),
                    "metadata": metadata,
                }
            )

    biology_path = root / "data/environment/earth-extremophile-studies.json"
    if biology_path.is_file():
        try:
            studies = json.loads(biology_path.read_text()).get("records", [])
        except (OSError, json.JSONDecodeError):
            studies = []
        for metadata in studies:
            place = places.get(str(metadata.get("place_id")))
            if place is None:
                continue
            place["observations"].append(
                {
                    "id": str(metadata["observation_id"]),
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("source_product_id"),
                    "source_url": metadata.get("source_url"),
                    "provider": metadata.get("provider"),
                    "acquired_at": metadata.get("temporal_coverage"),
                    "kind": "literature_context",
                    "measurements": metadata.get("measurements", []),
                    "metadata": metadata,
                }
            )

    # Link images to their Earth place; unknown labels remain unreviewed.
    for group, rows in grouped.items():
        if not include_unreviewed and not any(row.label_status == "verified" for row in rows):
            continue
        place_id = "earth-pilot-" + _normal_group(group.removeprefix("earth_"))
        place = places.get(place_id)
        if place is None and rows:
            first = rows[0]
            place = next(
                (
                    candidate
                    for candidate in places.values()
                    if candidate["body"] == "earth"
                    and _distance_km(
                        candidate["latitude_deg"],
                        candidate["longitude_east_deg"],
                        first.latitude,
                        first.longitude,
                    )
                    < 15
                ),
                None,
            )
        if place is None:
            continue
        for row in rows:
            if not include_unreviewed and row.label_status != "verified":
                continue
            place["observations"].append(
                {
                    "id": row.image_id,
                    "dataset_id": row.source_id,
                    "product_id": row.source_id,
                    "source_url": row.source_url,
                    "provider": row.provider,
                    "acquired_at": row.acquired_at,
                    "kind": "imagery",
                    "label": row.label,
                    "label_status": row.label_status,
                    "units": "image pixels",
                    "spatial_scale_m": row.native_gsd_m,
                    "latitude_deg": row.latitude,
                    "longitude_east_deg": row.longitude % 360,
                    "width_m": row.width_m,
                    "height_m": row.height_m,
                    "crs": row.crs,
                    "local_path": row.path,
                }
            )

    for row in records:
        if row.body != "mars":
            continue
        if not include_unreviewed and row.label_status != "verified":
            continue
        place = next(
            (
                candidate
                for candidate in places.values()
                if any(item["id"] == row.image_id for item in candidate["observations"])
            ),
            None,
        )
        if place is None:
            continue
        place["observations"].append(
            {
                "id": row.image_id,
                "dataset_id": row.source_id,
                "product_id": row.source_id,
                "source_url": row.source_url,
                "provider": row.provider,
                "acquired_at": row.acquired_at,
                "kind": "imagery",
                "label": row.label,
                "label_status": row.label_status,
                "units": "image pixels",
                "spatial_scale_m": row.native_gsd_m,
                "latitude_deg": row.latitude,
                "longitude_east_deg": row.longitude % 360,
                "width_m": row.width_m,
                "height_m": row.height_m,
                "crs": row.crs,
                "local_path": row.path,
            }
        )

    return sorted(
        places.values(), key=lambda item: (item["body"], item["name"].casefold(), item["id"])
    )


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float, body: str = "earth") -> float:
    r = {"earth": 6371.0, "mars": 3396.19, "moon": 1737.4}.get(body, 6371.0)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _dimension_evidence(place: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    root = root or Path(__file__).resolve().parents[2]
    observations = place["observations"]
    terrain = [
        o
        for o in observations
        if o.get("dataset_id")
        in {
            "cop-dem-glo-30",
            "nasadem-hgt",
            "mola-meg128",
            "lro-lola-gdr-ldem-64",
            "lro-lola-gdr-polar-ldem-120m",
        }
        and o.get("measurements")
    ]
    geology = [o for o in observations if str(o.get("dataset_id", "")).startswith("usgs-")]
    thermal = [
        o
        for o in observations
        if o.get("dataset_id")
        in {
            "lro-diviner-gdr-level3-st-clc",
            "lro-diviner-prp-south-polar",
            "mgs-tes-derived-thermal-inertia",
            "nasa-power-climatology",
            "era5-earth-candidate-climatology",
        }
    ]
    wind = [
        o
        for o in observations
        if o.get("dataset_id") in {"nasa-power-climatology", "era5-earth-candidate-climatology"}
    ]
    biology = [o for o in observations if o.get("dataset_id") == "earth-extremophile-studies"]
    meda = [o for o in observations if o.get("dataset_id") == "mars2020-meda"]
    rover_places = [
        o for o in observations if o.get("dataset_id") == "mars2020-rover-places-best-tactical"
    ]
    moisture_context = [
        *[o for o in biology if "water_resources" in o.get("metadata", {}).get("dimensions", [])],
        *[
            o
            for o in wind
            if any(
                m.get("name") == "RH2M"
                or m.get("name") == "ERA5 average monthly precipitation total"
                for m in o.get("measurements", [])
            )
        ],
        *[o for o in observations if o.get("dataset_id") == "lro-mini-rf-south-polar-cpr"],
        *[o for o in observations if o.get("dataset_id") == "lro-lend-south-polar-alds"],
        *[o for o in observations if o.get("dataset_id") == "lro-diviner-prp-south-polar"],
    ]
    assignments = {
        "terrain": terrain,
        "geology_materials": geology,
        "thermal_illumination": [
            *thermal,
            *[
                o
                for o in meda
                if "thermal_illumination" in o.get("metadata", {}).get("dimensions", [])
            ],
        ],
        "dust_processes": [
            *wind,
            *[o for o in meda if "dust_processes" in o.get("metadata", {}).get("dimensions", [])],
        ],
        "biology_habitability": biology,
        # Reuse DEM measurements as an explicitly limited terrain hazard proxy.
        "mission_operations": [*terrain, *rover_places],
        "water_resources": [
            *moisture_context,
            *[o for o in meda if "water_resources" in o.get("metadata", {}).get("dimensions", [])],
        ],
    }
    result = []
    for key, spec in DIMENSIONS.items():
        matching = assignments.get(key, [])
        context_evidence: list[dict[str, Any]] = []
        if key == "subsurface" and place.get("candidate_type") in {
            "lunar_volcanic_lava_tube",
            "volcanic_lava_tubes",
            "terrestrial_caves",
        }:
            context_evidence.append(
                {
                    "id": f"{place['id']}:catalogue-subsurface-context",
                    "kind": "interpreted",
                    "label": "Catalogue cave or pit interpretation",
                    "summary": place.get(
                        "basis", "Candidate subsurface context; not independently verified."
                    ),
                    "source_url": place.get("source_url"),
                    "location": {
                        "latitude_deg": place.get("latitude_deg"),
                        "longitude_east_deg": place.get("longitude_east_deg"),
                        "body": place.get("body"),
                    },
                    "uncertainty": (
                        "Candidate-region description only; no surveyed subsurface "
                        "geometry is indexed."
                    ),
                }
            )
        if (
            key == "mission_operations"
            and place.get("candidate_type") == "mars_landing_exploration"
        ):
            context_evidence.append(
                {
                    "id": f"{place['id']}:catalogue-mission-context",
                    "kind": "interpreted",
                    "label": "Known mission-site context",
                    "summary": place.get(
                        "basis", "Mission-site context; operational records are not indexed."
                    ),
                    "source_url": place.get("source_url"),
                    "location": {
                        "latitude_deg": place.get("latitude_deg"),
                        "longitude_east_deg": place.get("longitude_east_deg"),
                        "body": place.get("body"),
                    },
                    "uncertainty": (
                        "Published drive-position fixes are discrete locations, not a "
                        "continuous wheel path or a vehicle-performance assessment."
                    ),
                }
            )
        scoring_measurements: list[dict[str, Any]] = []
        scoring_exclusions: list[str] = []
        if key in {"terrain", "mission_operations"}:
            for observation in matching:
                measurement_rows = observation.get("measurements", [])
                if key == "mission_operations":
                    measurement_rows = [
                        row
                        for row in measurement_rows
                        if row.get("name") in OPERATIONS_PROXY_VARIABLES
                    ]
                metadata = observation.get("metadata", {})
                fraction = metadata.get("observed_cell_fraction")
                if (
                    observation.get("dataset_id") in {"mola-meg128", "lro-lola-gdr-polar-ldem-120m"}
                    and isinstance(fraction, (int, float))
                    and fraction < MIN_MOLA_OBSERVED_FRACTION
                ):
                    scoring_exclusions.append(
                        f"{observation.get('id')}: observed-cell support {fraction:.1%} "
                        f"is below the {MIN_MOLA_OBSERVED_FRACTION:.0%} comparison threshold."
                    )
                    continue
                scoring_measurements.extend(measurement_rows)
        status = "available" if matching else "not_observed"
        summary = (
            "Source-backed observation is linked to this place."
            if matching
            else "No compatible, place-specific measurement is indexed in ENOM."
        )
        if key == "terrain" and scoring_exclusions:
            status = "partial_coverage" if not scoring_measurements else "available"
            summary = "; ".join(scoring_exclusions)
        if key == "geology_materials" and matching:
            mapped = [o for o in matching if o.get("classification_status") == "mapped"]
            statuses = {o.get("classification_status") for o in matching}
            status = (
                "available"
                if mapped
                else "uncertain"
                if "boundary_ambiguous" in statuses
                else "outside_coverage"
                if "outside_map_extent" in statuses
                else "unmapped"
            )
            summary = (
                "; ".join(
                    (f"Mapped interpretation {o.get('map_unit_code') or ''} "
                     f"{o.get('map_unit_interpretation') or o.get('map_unit_name') or ''}").strip()
                    for o in mapped
                )
                if mapped
                else "USGS map point query returned no single mapped unit: "
                + ", ".join(sorted(str(value) for value in statuses))
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "nasa-power-climatology" for o in matching
        ):
            summary = (
                "NASA POWER gridded climatology provides annual and monthly "
                "Earth temperature and solar-radiation context; these are "
                "estimates, not local sensor observations."
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "era5-earth-candidate-climatology" for o in matching
        ):
            summary = (
                "ERA5 provides 1991–2020 Earth 2 m air-temperature climatology "
                "at the nearest roughly 25 km grid point. It is reanalysis "
                "context, not a local sensor or a lunar/Martian "
                "surface-temperature match."
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "lro-diviner-gdr-level3-st-clc" for o in matching
        ):
            summary = (
                "LRO Diviner provides derived nighttime lunar regolith surface "
                "temperature in kelvin. It is not Earth air temperature or an "
                "illumination measurement."
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "lro-diviner-prp-south-polar" for o in matching
        ):
            summary = (
                "Diviner's south-polar resource product gives first-mapping-year "
                "thermal-model estimates of annual lunar surface temperatures. "
                "These are lunar-only context, not paired Earth measurements, "
                "and are not scored across bodies."
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "mgs-tes-derived-thermal-inertia" for o in matching
        ):
            summary = (
                "MGS TES provides derived Mars nighttime thermal inertia. "
                "Thermal inertia is not temperature; ENOM does not compare it "
                "with Earth air temperature."
            )
        if key == "thermal_illumination" and any(
            o.get("dataset_id") == "mars2020-meda" for o in matching
        ):
            summary = (
                "Perseverance MEDA provides calibrated local air-temperature "
                "samples for one Martian sol at Jezero. This short sample is not "
                "a seasonal climate record and is not scored against Earth "
                "climatology."
            )
        if key == "dust_processes" and matching:
            if any(o.get("dataset_id") == "mars2020-meda" for o in matching):
                summary = (
                    "NASA POWER and ERA5 supply Earth wind climatologies; "
                    "Perseverance MEDA supplies one sol of rover wind samples at "
                    "Jezero. Their heights, time coverage, and sampling differ; none "
                    "directly measures dust activity or erosion, and none is scored."
                )
            else:
                summary = (
                    "NASA POWER and ERA5 provide Earth 10 m wind climatologies; they "
                    "do not directly measure dust events, erosion, or surface change."
                )
        if key == "biology_habitability":
            summary = (
                f"{len(matching)} peer-reviewed Earth study reference(s) "
                "are linked to this region. "
                "They describe Earth organisms or their environment; they do not support claims "
                "of life or biosignatures beyond Earth and are not used to score analogues."
                if matching
                else (
                    "No place-linked Earth extremophile study is indexed for this "
                    "candidate. ENOM does not score or claim extraterrestrial life "
                    "or biosignatures."
                )
            )
            if matching:
                status = "context_only"
        if key == "water_resources" and matching:
            status = "context_only"
            has_air_humidity = any(
                o.get("dataset_id") in {"nasa-power-climatology", "mars2020-meda"} for o in matching
            )
            has_era5_precipitation = any(
                o.get("dataset_id") == "era5-earth-candidate-climatology" for o in matching
            )
            has_soil_moisture = any(
                o.get("dataset_id") == "earth-extremophile-studies" for o in matching
            )
            notes = []
            if has_air_humidity:
                if any(o.get("dataset_id") == "mars2020-meda" for o in matching):
                    notes.append(
                        "MEDA measures Martian atmospheric relative humidity for one "
                        "sol, not soil water, ground ice, or a usable resource"
                    )
                if any(o.get("dataset_id") == "nasa-power-climatology" for o in matching):
                    notes.append(
                        "NASA POWER two-metre relative humidity is an Earth gridded "
                        "climatology/reanalysis estimate, not a surface-water or "
                        "ground-ice measurement"
                    )
            if has_soil_moisture:
                notes.append(
                    "Yungay field-study humidity and water-activity readings "
                    "describe sampled subsurface soil, not a recoverable reserve"
                )
            if has_era5_precipitation:
                notes.append(
                    "ERA5 precipitation is gridded weather context, not a "
                    "measurement of soil water, groundwater, or accessible resources"
                )
            if any(o.get("dataset_id") == "lro-mini-rf-south-polar-cpr" for o in matching):
                notes.append(
                    "Mini-RF CPR is a radar backscatter ratio that can also reflect "
                    "rough or blocky surfaces; it is not a unique ice detector"
                )
            if any(o.get("dataset_id") == "lro-lend-south-polar-alds" for o in matching):
                notes.append(
                    "LEND neutron count rates are indirect hydrogen context and do "
                    "not directly measure water or ice; the 0.5° map cell is broader "
                    "than a specific landing spot"
                )
            if any(o.get("dataset_id") == "lro-diviner-prp-south-polar" for o in matching):
                notes.append(
                    "Diviner PRP ice-stability depth is a thermal-model estimate, "
                    "not a direct detection of ice or an estimate of accessible "
                    "reserves"
                )
            summary = "; ".join(notes) + ". These data are context only and are not scored."
        if key == "subsurface":
            summary = (
                "Catalogue interpretations are clues; possible openings are not "
                "treated as confirmed caves."
            )
        if key == "mission_operations":
            has_operations_proxy = any(
                row.get("availability") == "available" for row in scoring_measurements
            )
            has_rover_records = any(
                o.get("dataset_id") == "mars2020-rover-places-best-tactical" for o in matching
            )
            status = "available" if has_operations_proxy or has_rover_records else "not_observed"
            summary = (
                (
                    "The DEM provides slope, local height changes, and roughness as "
                    "a terrain proxy. At Jezero, NASA PLACES also supplies discrete "
                    "Perseverance locations associated with drives. Those points do "
                    "not show the exact wheel path or assess vehicle safety."
                )
                if has_operations_proxy and has_rover_records
                else (
                    "The DEM provides slope, local height changes, and roughness as "
                    "a terrain proxy. NASA PLACES supplies discrete Perseverance "
                    "locations associated with drives; they do not show the exact "
                    "wheel path or assess vehicle safety."
                )
                if has_rover_records
                else (
                    "The DEM provides slope, local height changes, and roughness. "
                    "ENOM compares these as clues about landing or rover movement; "
                    "it does not test a specific vehicle or tell whether a mission "
                    "is safe."
                )
                if has_operations_proxy
                else (
                    "No compatible slope or roughness measurements are linked here, "
                    "so ENOM cannot compare landing or rover movement. Mission logs "
                    "and vehicle limits are also missing."
                )
            )
        displayed_measurements = []
        for observation in matching:
            measurements = observation.get("measurements", [])
            if (
                key == "mission_operations"
                and observation.get("dataset_id") != "mars2020-rover-places-best-tactical"
            ):
                measurements = [
                    row for row in measurements if row.get("name") in OPERATIONS_PROXY_VARIABLES
                ]
            if observation.get("dataset_id") == "nasa-power-climatology":
                if key == "thermal_illumination":
                    measurements = [
                        m for m in measurements if m.get("name") in {"T2M", "ALLSKY_SFC_SW_DWN"}
                    ]
                elif key == "dust_processes":
                    measurements = [m for m in measurements if m.get("name") == "WS10M"]
                elif key == "water_resources":
                    measurements = [m for m in measurements if m.get("name") == "RH2M"]
            if observation.get("dataset_id") == "era5-earth-candidate-climatology":
                expected_name = {
                    "thermal_illumination": "ERA5 monthly mean 2 m air temperature",
                    "dust_processes": "ERA5 monthly mean 10 m wind speed",
                    "water_resources": "ERA5 average monthly precipitation total",
                }.get(key)
                measurements = [m for m in measurements if m.get("name") == expected_name]
            if observation.get("dataset_id") == "mars2020-meda":
                if observation.get("metadata", {}).get("dimensions") != [key]:
                    measurements = []
            displayed_measurements.extend(measurements)
        evidence_items = []
        for observation in matching:
            metadata = observation.get("metadata", {})
            evidence_measurements = observation.get("measurements", [])
            if (
                key == "mission_operations"
                and observation.get("dataset_id") != "mars2020-rover-places-best-tactical"
            ):
                evidence_measurements = [
                    row
                    for row in evidence_measurements
                    if row.get("name") in OPERATIONS_PROXY_VARIABLES
                ]
            if observation.get("dataset_id") == "nasa-power-climatology":
                if key == "thermal_illumination":
                    evidence_measurements = [
                        m
                        for m in evidence_measurements
                        if m.get("name") in {"T2M", "ALLSKY_SFC_SW_DWN"}
                    ]
                elif key == "dust_processes":
                    evidence_measurements = [
                        m for m in evidence_measurements if m.get("name") == "WS10M"
                    ]
                elif key == "water_resources":
                    evidence_measurements = [
                        m for m in evidence_measurements if m.get("name") == "RH2M"
                    ]
            if observation.get("dataset_id") == "era5-earth-candidate-climatology":
                expected_name = {
                    "thermal_illumination": "ERA5 monthly mean 2 m air temperature",
                    "dust_processes": "ERA5 monthly mean 10 m wind speed",
                    "water_resources": "ERA5 average monthly precipitation total",
                }.get(key)
                evidence_measurements = [
                    m for m in evidence_measurements if m.get("name") == expected_name
                ]
            if observation.get("dataset_id") == "mars2020-meda" and observation.get(
                "metadata", {}
            ).get("dimensions") != [key]:
                evidence_measurements = []
            interpreted = observation.get("kind") == "geologic_interpretation"
            evidence_kind = (
                str(metadata.get("evidence_kind", "interpreted"))
                if observation.get("kind") in {"literature_context", "measurement"}
                else "interpreted"
                if interpreted
                else "derived"
            )
            evidence_items.append(
                {
                    "id": observation["id"],
                    "kind": evidence_kind,
                    "dataset_id": observation.get("dataset_id"),
                    "product_id": observation.get("product_id"),
                    "provider": observation.get("provider"),
                    "source_url": observation.get("source_url"),
                    "location": {
                        "body": place.get("body"),
                        "latitude_deg": metadata.get("latitude_deg", place.get("latitude_deg")),
                        "longitude_east_deg": metadata.get(
                            "longitude_east_deg", place.get("longitude_east_deg")
                        ),
                    },
                    "spatial_coverage": {
                        "location_precision": metadata.get("location_precision"),
                        "context_size_m": metadata.get("context_size_m"),
                        "spatial_scale_m": next(
                            (
                                m.get("spatial_scale_m")
                                for m in evidence_measurements
                                if m.get("spatial_scale_m") is not None
                            ),
                            None,
                        ),
                        "grid_spacing_deg": metadata.get("grid_spacing_deg"),
                        "nominal_cartographic_scale": metadata.get("nominal_cartographic_scale"),
                        "coverage_fraction": metadata.get(
                            "valid_pixel_fraction", metadata.get("observed_cell_fraction")
                        ),
                        "sample_count": next(
                            (
                                m.get("sample_count")
                                for m in evidence_measurements
                                if m.get("sample_count") is not None
                            ),
                            None,
                        ),
                    },
                    "temporal_coverage": observation.get("acquired_at")
                    or metadata.get("period")
                    or metadata.get("observation_period"),
                    "measurements": evidence_measurements,
                    "units": sorted(
                        {str(m.get("units")) for m in evidence_measurements if m.get("units")}
                    ),
                    "summary": metadata.get("summary"),
                    "interpretation": {
                        "classification_status": observation.get("classification_status"),
                        "map_unit_code": observation.get("map_unit_code"),
                        "map_unit_name": observation.get("map_unit_name"),
                        "summary": metadata.get("map_unit_interpretation")
                        or metadata.get("map_unit_description"),
                    }
                    if interpreted
                    else None,
                    "study_region": metadata.get("study_region"),
                    "spatial_relation": metadata.get("spatial_relation"),
                    "use_limit": metadata.get("use_limit"),
                    "quality_note": metadata.get("quality_note"),
                    "uncertainty": metadata.get("uncertainty")
                    or next(
                        (
                            m.get("uncertainty")
                            for m in evidence_measurements
                            if m.get("uncertainty")
                        ),
                        None,
                    ),
                    "measurement_semantics": metadata.get("measurement_semantics"),
                    "interpretation_note": metadata.get("interpretation"),
                }
            )
        result.append(
            {
                "id": key,
                "label": spec["label"],
                "status": status,
                "summary": summary,
                "observation_ids": [o["id"] for o in matching],
                "sources": [
                    {
                        "dataset_id": o.get("dataset_id"),
                        "product_id": o.get("product_id"),
                        "provider": o.get("provider"),
                        "url": o.get("source_url"),
                    }
                    for o in matching
                ],
                "measurements": displayed_measurements,
                "evidence_items": evidence_items,
                "context_evidence": context_evidence,
                "interpretations": [
                    {
                        "observation_id": o["id"],
                        "dataset_id": o.get("dataset_id"),
                        "classification_status": o.get("classification_status"),
                        "map_unit_code": o.get("map_unit_code"),
                        "map_unit_name": o.get("map_unit_name"),
                        "map_unit_age": o.get("metadata", {}).get("map_unit_age"),
                        "map_unit_age_min": o.get("metadata", {}).get("map_unit_age_min"),
                        "map_unit_age_max": o.get("metadata", {}).get("map_unit_age_max"),
                        "map_unit_description": o.get("metadata", {}).get("map_unit_description"),
                        "map_unit_interpretation": o.get("map_unit_interpretation"),
                        "major_materials": o.get("metadata", {}).get("major_materials", []),
                        "state": o.get("metadata", {}).get("state"),
                        "map_reference": o.get("metadata", {}).get("reference"),
                        "ngmdb_urls": o.get("metadata", {}).get("ngmdb_urls", []),
                        "digital_data_url": o.get("metadata", {}).get("digital_data_url"),
                        "candidate_unit_codes": o.get("metadata", {}).get(
                            "candidate_unit_codes", []
                        ),
                        "nominal_cartographic_scale": o.get("metadata", {}).get(
                            "nominal_cartographic_scale"
                        ),
                        "source_description": o.get("metadata", {}).get("source_description"),
                        "source_url": o.get("source_url"),
                    }
                    for o in matching
                    if key == "geology_materials"
                ],
                "scoring_measurements": scoring_measurements,
                "scoring_exclusions": scoring_exclusions,
                "location": {
                    "body": place.get("body"),
                    "latitude_deg": place.get("latitude_deg"),
                },
                "prototype_context": {
                    key: place.get(key)
                    for key in ("candidate_type", "basis", "source_url")
                    if place.get(key) is not None
                },
                "source_guides": SOURCE_GUIDES[key],
                "source_connections": [
                    {
                        **source,
                        "place_status": (
                            "outside_coverage"
                            if source.get("dataset_id")
                            and any(
                                o.get("dataset_id") == source["dataset_id"]
                                and o.get("classification_status") == "outside_map_extent"
                                for o in observations
                            )
                            else "boundary_ambiguous"
                            if source.get("dataset_id")
                            and any(
                                o.get("dataset_id") == source["dataset_id"]
                                and o.get("classification_status") == "boundary_ambiguous"
                                for o in observations
                            )
                            else "observed_here"
                            if source.get("dataset_id")
                            and any(
                                o.get("dataset_id") == source["dataset_id"]
                                and o.get("classification_status")
                                not in {"outside_map_extent", "outside_coverage"}
                                for o in observations
                            )
                            else "available_elsewhere"
                            if source.get("status") == "operational"
                            else source.get("status")
                        ),
                    }
                    for source in source_inventory(root)
                    if source["dimension"] == key
                ],
            }
        )
    return result


def _comparable_site_measurements(dimension: dict[str, Any]) -> list[dict[str, Any]]:
    """Collapse repeat observations only when their units and scales agree."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dimension.get("scoring_measurements", dimension.get("measurements", [])):
        value = row.get("value")
        if (
            row.get("availability") != "available"
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            continue
        grouped[str(row.get("name"))].append(row)
    aggregated = []
    for name, rows in grouped.items():
        units = {row.get("units") for row in rows}
        raw_scales = [row.get("spatial_scale_m") for row in rows]
        scales = [
            float(scale)
            for scale in raw_scales
            if not isinstance(scale, bool)
            and isinstance(scale, (int, float))
            and math.isfinite(scale)
            and scale > 0
        ]
        if len(units) != 1 or len(scales) != len(rows):
            continue
        if max(scales) / min(scales) > 1.05:
            continue
        aggregated.append(
            {
                "name": name,
                "value": median(float(row["value"]) for row in rows),
                "units": next(iter(units)),
                "availability": "available",
                "spatial_scale_m": median(float(scale) for scale in scales),
            }
        )
    return aggregated


@lru_cache(maxsize=4)
def candidate_context_records(root: Path) -> list[dict[str, Any]]:
    """Return source-linked catalogue context, clearly separate from measurements."""
    catalogue_path = root / "data/manifests/candidate-locations.json"
    if not catalogue_path.is_file():
        return []
    try:
        entries = json.loads(catalogue_path.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, json.JSONDecodeError):
        return []
    subsurface_types = {"lunar_volcanic_lava_tube", "volcanic_lava_tubes", "terrestrial_caves"}
    result = []
    for entry in entries:
        candidate_type = entry.get("candidate_type")
        if candidate_type in subsurface_types:
            dataset_id = "candidate-subsurface-context"
            context_type = "cave_or_pit_catalogue_interpretation"
        elif candidate_type == "mars_landing_exploration":
            dataset_id = "candidate-mission-site-context"
            context_type = "planetary_mission_site_description"
        else:
            continue
        result.append(
            {
                "id": f"{entry['id']}:catalogue-context",
                "place_id": entry["id"],
                "name": entry["name"],
                "body": entry["body"],
                "candidate_type": candidate_type,
                "context_type": context_type,
                "dataset_id": dataset_id,
                "evidence_kind": "interpreted",
                "latitude_deg": entry["latitude_deg"],
                "longitude_east_deg": entry["longitude_east_deg"],
                "summary": entry.get("basis"),
                "source_url": entry.get("source_url"),
                "measurement_status": "no_measurement",
            }
        )
    return result


@lru_cache(maxsize=4)
def source_inventory(root: Path) -> list[dict[str, Any]]:
    """Report actual checked-in source coverage separately from planned connections."""
    available_rows: list[dict[str, Any]] = []
    for directory in (root / "data/terrain", root / "data/geology"):
        for path in directory.glob("*.tif.json" if directory.name == "terrain" else "*.json"):
            try:
                available_rows.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
    power_path = root / "data/environment/nasa-power-climatology.json"
    if power_path.is_file():
        try:
            power_records = json.loads(power_path.read_text()).get("records", [])
            available_rows.extend(power_records)
        except (OSError, json.JSONDecodeError):
            pass
    era5_path = root / "data/environment/era5-earth-candidate-climatology.json"
    if era5_path.is_file():
        try:
            available_rows.extend(
                json.loads(era5_path.read_text(encoding="utf-8")).get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    lend_path = root / "data/environment/lro-lend-south-polar-alds.json"
    if lend_path.is_file():
        try:
            available_rows.extend(
                json.loads(lend_path.read_text(encoding="utf-8")).get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    diviner_prp_path = root / "data/environment/lro-diviner-south-polar-prp.json"
    if diviner_prp_path.is_file():
        try:
            available_rows.extend(
                json.loads(diviner_prp_path.read_text(encoding="utf-8")).get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    rover_places_path = root / "data/environment/mars2020-jezero-rover-places.json"
    if rover_places_path.is_file():
        try:
            rover_payload = json.loads(rover_places_path.read_text(encoding="utf-8"))
            available_rows.extend(
                {
                    **row,
                    "dataset_id": rover_payload.get("dataset_id"),
                    "provider": rover_payload.get("provider"),
                    "source_url": rover_payload.get("source_url"),
                }
                for row in rover_payload.get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    minirf_path = root / "data/environment/lro-mini-rf-south-polar-cpr.json"
    if minirf_path.is_file():
        try:
            available_rows.extend(
                json.loads(minirf_path.read_text(encoding="utf-8")).get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    meda_path = root / "data/environment/mars2020-meda-sol100.json"
    if meda_path.is_file():
        try:
            available_rows.extend(
                json.loads(meda_path.read_text(encoding="utf-8")).get("records", [])
            )
        except (OSError, json.JSONDecodeError):
            pass
    biology_path = root / "data/environment/earth-extremophile-studies.json"
    if biology_path.is_file():
        try:
            available_rows.extend(json.loads(biology_path.read_text()).get("records", []))
        except (OSError, json.JSONDecodeError):
            pass
    available_rows.extend(candidate_context_records(root))
    output = []
    for source in SOURCE_CATALOGUE:
        row = dict(source)
        dataset_id = row.get("dataset_id")
        rows = [
            item for item in available_rows if dataset_id and item.get("dataset_id") == dataset_id
        ]
        if dataset_id == "nasa-power-climatology":
            rows = [
                item
                for item in rows
                if any(
                    measurement.get("availability") == "available"
                    for measurement in item.get("measurements", [])
                )
            ]
        if row.get("measurement_names"):
            accepted_names = set(row["measurement_names"])
            rows = [
                item
                for item in rows
                if any(
                    measurement.get("name") in accepted_names
                    for measurement in item.get("measurements", [])
                )
            ]
        elif dataset_id == "usgs-earth-sgmc":
            rows = [
                item
                for item in rows
                if item.get("classification_status") in {"mapped", "boundary_ambiguous"}
            ]
        row["coverage_count"] = len(rows)
        if row["status"] == "operational" and not rows:
            row["status"] = "registered"
        output.append(row)
    return output


def discover(
    root: Path,
    target_id: str,
    profile_id: str,
    weights: dict[str, float] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    if profile_id not in PROFILES:
        raise ValueError(f"Unknown profile '{profile_id}'")
    selected_weights = validate_dimension_weights(
        PROFILES[profile_id]["weights"] if weights is None else weights
    )
    places = build_places(root)
    target = next((p for p in places if p["id"] == target_id), None)
    if target is None:
        target = next(
            (p for p in places if any(o["id"] == target_id for o in p["observations"])), None
        )
    if target is None:
        raise KeyError(target_id)
    target_dimensions = _dimension_evidence(target, root)
    results = []
    for candidate in places:
        if candidate["body"] != "earth" or candidate["id"] == target_id:
            continue
        dims = _dimension_evidence(candidate, root)
        dimension_comparison = compare_dimensions(target_dimensions, dims, selected_weights)
        dimension_rows = dimension_comparison["dimension_scores"]
        score = dimension_comparison["score"]
        results.append(
            {
                "place": {
                    k: candidate[k]
                    for k in (
                        "id",
                        "name",
                        "body",
                        "longitude_east_deg",
                        "latitude_deg",
                        "status",
                        "basis",
                        "source_url",
                    )
                },
                "layers": _place_layers(root, candidate),
                "score": score,
                "score_interpretation": (
                    "Eight-dimension prototype similarity; not a probability, "
                    "validated geological analogue, or mission suitability."
                ),
                "evidence_coverage": dimension_comparison["evidence_coverage"],
                "prototype_similarity": dimension_comparison["prototype_similarity"],
                "observed_similarity": dimension_comparison["observed_similarity"],
                "source_context_coverage": dimension_comparison["source_context_coverage"],
                "measured_weight_coverage": dimension_comparison["measured_weight_coverage"],
                "estimated_weight_coverage": dimension_comparison["estimated_weight_coverage"],
                "simulated_weight_coverage": dimension_comparison["simulated_weight_coverage"],
                "dimension_scores": dimension_rows,
                "missing_dimensions": dimension_comparison["missing_dimensions"],
                "evidence_class": dimension_comparison["evidence_class"],
                "matched_weight": sum(d["effective_weight"] for d in dimension_rows),
                "weighted_dimensions_scored": [
                    d["id"] for d in dimension_rows if d["scored"] and d["weight"] > 0
                ],
                "mission_suitability": {
                    "status": "not_assessed",
                    "note": (
                        "Mission suitability requires a separate vehicle-specific "
                        "engineering and operational assessment."
                    ),
                },
            }
        )
    results.sort(
        key=lambda item: (item["score"] is None, -(item["score"] or 0), item["place"]["id"])
    )
    for index, item in enumerate(results[:limit], start=1):
        item["rank"] = index if item["score"] is not None else None
    return {
        "target": {
            k: target[k]
            for k in ("id", "name", "body", "longitude_east_deg", "latitude_deg", "status")
        },
        "target_evidence": target_dimensions,
        "target_layers": _place_layers(root, target),
        "profile": {
            "id": profile_id,
            "name": PROFILES[profile_id]["name"],
            "description": PROFILES[profile_id]["description"],
        },
        "weights": selected_weights,
        "results": results[:limit],
        "search_scope": "ENOM's current candidate and pilot place catalogue; not a global search.",
        "unique_place_count": len({item["place"]["id"] for item in results[:limit]}),
        "limitations": [
            (
                "Every dimension contributes a measured score, an explicitly "
                "labelled estimate, or a neutral simulation to the prototype. "
                "Only source-backed comparable evidence contributes to evidence coverage."
            ),
            (
                "Environmental proxies do not replace matched surface-temperature, "
                "water-resource, dust-transport, biological, or cave-geometry "
                "measurements. Terrain and operations share one evidence budget."
            ),
            (
                "Uncertainty notes are displayed, but terrain scores do not yet "
                "propagate measurement uncertainty or correct cross-dataset "
                "systematic bias."
            ),
            (
                "Earth pilot morphology labels are unknown unless the underlying "
                "observation explicitly says otherwise."
            ),
            (
                "A similarity ranking does not establish mission suitability, "
                "resource usability, or a validated analogue."
            ),
            (
                "Small georeferenced terrain windows support separate, "
                "side-by-side Earth and planetary views. High-resolution image "
                "overlays and geology polygon overlays are not locally "
                "available; geology is point-map context only."
            ),
        ],
    }


def _display_crs(body: str, metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = (
        metadata.get("processing_crs")
        or metadata.get("crs")
        or metadata.get("grid_crs")
        or metadata.get("coordinate_reference_system")
    )
    if not raw:
        return None, None
    raw_text = str(raw)
    if raw_text.startswith("EPSG:"):
        return raw_text, raw_text
    if metadata.get("dataset_id") == "lro-lola-gdr-polar-ldem-120m":
        return "Moon south-polar stereographic (DE421 frame)", raw_text
    if body == "mars":
        return "Mars equirectangular (east-positive; 3,396 km radius)", raw_text
    if body == "moon":
        return "Moon equirectangular (1,737.4 km radius)", raw_text
    return "Source map coordinates (see full source metadata)", raw_text


def _place_layers(root: Path, place: dict[str, Any]) -> list[dict[str, Any]]:
    layers = []
    images = [item for item in place["observations"] if item.get("kind") == "imagery"]
    if images:
        local_images = [
            item
            for item in images
            if item.get("local_path") and (root / item["local_path"]).is_file()
        ]
        layers.append(
            {
                "id": "surface_imagery",
                "label": "Source surface imagery",
                "status": "available" if local_images else "metadata_only",
                "body": place["body"],
                "crs": sorted({str(item["crs"]) for item in local_images if item.get("crs")}),
                "observations": [
                    {
                        "id": item["id"],
                        "url": f"/api/observations/{item['id']}/image",
                        "source_url": item.get("source_url"),
                        "acquired_at": item.get("acquired_at"),
                        "latitude_deg": item.get("latitude_deg"),
                        "longitude_east_deg": item.get("longitude_east_deg"),
                        "context_size_m": item.get("width_m"),
                        "crs": item.get("crs"),
                    }
                    for item in local_images
                ],
                "alignment_note": (
                    "Image patch coordinates and footprint are retained; this is not "
                    "an Earth-to-planet coordinate overlay."
                ),
            }
        )
    terrain = [
        item
        for item in place["observations"]
        if item.get("dataset_id")
        in {
            "cop-dem-glo-30",
            "nasadem-hgt",
            "mola-meg128",
            "lro-lola-gdr-ldem-64",
            "lro-lola-gdr-polar-ldem-120m",
        }
    ]
    if terrain:
        local_rasters = []
        for item in terrain:
            metadata = item.get("metadata", {})
            raster_path = metadata.get("output") or metadata.get("terrain_raster")
            if raster_path and (root / raster_path).is_file():
                display_crs, raw_crs = _display_crs(place["body"], metadata)
                local_rasters.append(
                    {
                        "id": item["id"],
                        "path": raster_path,
                        "crs": display_crs,
                        "crs_detail": raw_crs,
                        "source_url": item.get("source_url"),
                    }
                )
        display_crs_values = [
            _display_crs(place["body"], item.get("metadata", {}))[0] for item in terrain
        ]
        raw_crs_values = [
            _display_crs(place["body"], item.get("metadata", {}))[1] for item in terrain
        ]
        layers.append(
            {
                "id": "terrain_dem",
                "label": "Elevation / terrain",
                "status": "available" if local_rasters else "metadata_only",
                "body": place["body"],
                "crs": display_crs_values,
                "crs_detail": raw_crs_values,
                "alignment_group": local_rasters[0]["id"] if local_rasters else None,
                "url": f"/api/places/{place['id']}/layers/elevation.png" if local_rasters else None,
                "context_size_m": next(
                    (
                        item.get("metadata", {}).get("context_size_m")
                        for item in terrain
                        if item.get("metadata", {}).get("context_size_m")
                    ),
                    None,
                ),
                "observations": local_rasters
                if local_rasters
                else [{"id": item["id"], "source_url": item.get("source_url")} for item in terrain],
                "alignment_note": (
                    "Local 10.19 km raster window. Elevation colours are stretched "
                    "to this window's 2nd–98th percentile, so colour does not "
                    "represent the same absolute elevation between bodies. "
                    "Separate-body coordinates are never overlaid directly."
                ),
            }
        )
        layers.append(
            {
                "id": "terrain_slope",
                "label": "Slope / terrain hazard",
                "status": "available" if local_rasters else "metadata_only",
                "body": place["body"],
                "crs": display_crs_values,
                "crs_detail": raw_crs_values,
                "alignment_group": local_rasters[0]["id"] if local_rasters else None,
                "url": f"/api/places/{place['id']}/layers/slope.png" if local_rasters else None,
                "context_size_m": next(
                    (
                        item.get("metadata", {}).get("context_size_m")
                        for item in terrain
                        if item.get("metadata", {}).get("context_size_m")
                    ),
                    None,
                ),
                "observations": local_rasters,
                "alignment_note": (
                    "Slope is derived from the indexed DEM grid and displayed on a "
                    "fixed 0–30° colour scale (higher values clip). It is a regional "
                    "screening layer, not a vehicle-specific hazard limit."
                ),
            }
        )
        roughness_ids = {
            item["id"]
            for item in terrain
            if any(
                measurement.get("name") == "median_roughness_3x3"
                and measurement.get("availability") == "available"
                for measurement in item.get("measurements", [])
            )
        }
        roughness_rasters = [item for item in local_rasters if item["id"] in roughness_ids]
        layers.append(
            {
                "id": "terrain_roughness",
                "label": "3×3 DEM roughness",
                "status": "available" if roughness_rasters else "metadata_only",
                "body": place["body"],
                "crs": display_crs_values,
                "crs_detail": raw_crs_values,
                "url": f"/api/places/{place['id']}/layers/roughness.png"
                if roughness_rasters
                else None,
                "context_size_m": next(
                    (
                        item.get("metadata", {}).get("context_size_m")
                        for item in terrain
                        if item.get("metadata", {}).get("context_size_m")
                    ),
                    None,
                ),
                "observations": roughness_rasters
                or [{"id": item["id"], "source_url": item.get("source_url")} for item in terrain],
                "alignment_note": (
                    "Colour shows absolute elevation difference from the local 3×3 "
                    "DEM mean in metres; only complete neighborhoods are shown. The "
                    "definition matches ENOM's median_roughness_3x3 feature. Colours "
                    "are stretched within each source window and are not directly "
                    "comparable between bodies."
                ),
            }
        )
        coverage_observations = []
        coverage_rasters = []
        for item in terrain:
            metadata = item.get("metadata", {})
            count_path = metadata.get("count_raster")
            raster_path = metadata.get("output") or metadata.get("terrain_raster")
            if count_path and (root / count_path).is_file():
                coverage_kind = (
                    "direct_lola_shot_count"
                    if item.get("dataset_id") == "lro-lola-gdr-polar-ldem-120m"
                    else "instrument_count"
                )
                coverage_rasters.append(
                    {
                        "id": item["id"],
                        "path": count_path,
                        "source_url": metadata.get("counts_source_url") or item.get("source_url"),
                        "coverage_kind": coverage_kind,
                        "coverage_fraction": metadata.get("observed_cell_fraction"),
                        "crs": metadata.get("grid_crs") or metadata.get("processing_crs"),
                    }
                )
            elif (
                raster_path
                and (root / raster_path).is_file()
                and item.get("dataset_id") == "cop-dem-glo-30"
            ):
                coverage_rasters.append(
                    {
                        "id": item["id"],
                        "path": raster_path,
                        "source_url": item.get("source_url"),
                        "coverage_kind": "valid_grid_cells",
                        "coverage_fraction": metadata.get("valid_pixel_fraction"),
                        "crs": metadata.get("processing_crs"),
                    }
                )
            coverage_fraction = (
                metadata.get("observed_cell_fraction")
                if item.get("dataset_id") in {"mola-meg128", "lro-lola-gdr-polar-ldem-120m"}
                else metadata.get("valid_pixel_fraction")
                if item.get("dataset_id") == "cop-dem-glo-30"
                else None
            )
            coverage_kind = (
                "direct_lola_shot_count"
                if item.get("dataset_id") == "lro-lola-gdr-polar-ldem-120m"
                else "instrument_count"
                if item.get("dataset_id") == "mola-meg128"
                else "valid_grid_cells"
                if item.get("dataset_id") == "cop-dem-glo-30"
                else "not_quantified"
            )
            coverage_observations.append(
                {
                    "id": item["id"],
                    "source_url": item.get("source_url"),
                    "coverage_fraction": coverage_fraction,
                    "coverage_kind": coverage_kind,
                }
            )
        layers.append(
            {
                "id": "terrain_coverage",
                "label": "Terrain data coverage",
                "status": "available" if coverage_rasters else "metadata_only",
                "body": place["body"],
                "crs": display_crs_values,
                "crs_detail": raw_crs_values,
                "url": f"/api/places/{place['id']}/layers/coverage.png"
                if coverage_rasters
                else None,
                "context_size_m": next(
                    (
                        item.get("metadata", {}).get("context_size_m")
                        for item in terrain
                        if item.get("metadata", {}).get("context_size_m")
                    ),
                    None,
                ),
                "observations": [
                    {**item, "url": f"/api/places/{place['id']}/layers/coverage.png"}
                    for item in coverage_rasters
                ]
                or coverage_observations,
                "alignment_note": (
                    "Coverage means MOLA altimeter count support, LOLA polar "
                    "direct-shot support, or Copernicus valid DEM cells. Colours are "
                    "stretched within each local window and are not absolute between "
                    "places. Counts describe source support, not measurement "
                    "certainty."
                ),
            }
        )
    geology = [
        item for item in place["observations"] if item.get("kind") == "geologic_interpretation"
    ]
    if geology:
        layers.append(
            {
                "id": "geology_context",
                "label": "Geology map context",
                "status": "point_context",
                "body": place["body"],
                "crs": None,
                "context_size_m": None,
                "observations": [
                    {"id": item["id"], "source_url": item.get("source_url")} for item in geology
                ],
                "alignment_note": (
                    "A source map unit was queried at this place; ENOM does not have "
                    "the map polygons locally available to draw a geology overlay. "
                    "See the geology evidence for the mapped unit and map scale."
                ),
            }
        )
    thermal = [
        item
        for item in place["observations"]
        if item.get("dataset_id")
        in {"lro-diviner-gdr-level3-st-clc", "mgs-tes-derived-thermal-inertia"}
    ]
    if thermal:
        local_thermal = []
        for item in thermal:
            metadata = item.get("metadata", {})
            raster_path = metadata.get("output") or metadata.get("terrain_raster")
            if raster_path and (root / raster_path).is_file():
                local_thermal.append(
                    {
                        "id": item["id"],
                        "url": f"/api/places/{place['id']}/layers/thermal.png",
                        "source_url": item.get("source_url"),
                        "crs": metadata.get("coordinate_reference_system")
                        or metadata.get("grid_crs"),
                        "context_size_m": metadata.get("context_size_m"),
                        "acquired_at": item.get("acquired_at"),
                        "units": next(iter(item.get("measurements", [])), dict[str, Any]()).get(
                            "units"
                        ),
                        "value": next(iter(item.get("measurements", [])), dict[str, Any]()).get(
                            "value"
                        ),
                    }
                )
        layers.append(
            {
                "id": "thermal_context",
                "label": "Thermal source context",
                "status": "available" if local_thermal else "metadata_only",
                "body": place["body"],
                "crs": [
                    _display_crs(place["body"], item.get("metadata", {}))[0] for item in thermal
                ],
                "crs_detail": [
                    _display_crs(place["body"], item.get("metadata", {}))[1] for item in thermal
                ],
                "url": f"/api/places/{place['id']}/layers/thermal.png" if local_thermal else None,
                "context_size_m": next(
                    (
                        item.get("metadata", {}).get("context_size_m")
                        for item in thermal
                        if item.get("metadata", {}).get("context_size_m")
                    ),
                    None,
                ),
                "observations": local_thermal
                or [{"id": item["id"], "source_url": item.get("source_url")} for item in thermal],
                "alignment_note": (
                    "LRO Diviner is nighttime lunar surface temperature in K; MGS "
                    "TES is Mars thermal inertia, not temperature. Colours are "
                    "stretched within this source window and must not be compared as "
                    "the same quantity."
                ),
            }
        )
    minirf = [
        item
        for item in place["observations"]
        if item.get("dataset_id") == "lro-mini-rf-south-polar-cpr"
        and item.get("metadata", {}).get("grid_values")
    ]
    if minirf:
        layers.append(
            {
                "id": "mini_rf_cpr",
                "label": "Mini-RF radar CPR sample",
                "status": "available",
                "body": place["body"],
                "crs": "Moon south-polar stereographic; about 948 m per pixel",
                "url": f"/api/places/{place['id']}/layers/mini-rf-cpr.png",
                "context_size_m": 5 * 947.60470075467,
                "observations": [
                    {
                        "id": item["id"],
                        "url": f"/api/places/{place['id']}/layers/mini-rf-cpr.png",
                        "source_url": item.get("source_url"),
                        "acquired_at": item.get("acquired_at"),
                        "crs": "Moon south-polar stereographic; about 948 m per pixel",
                    }
                    for item in minirf
                ],
                "alignment_note": (
                    "The image shows only the 5×5 CPR sample around this "
                    "candidate-region centre, not the full radar mosaic. Colour uses "
                    "a fixed 0–1.5 CPR scale; higher values clip at 1.5. CPR can "
                    "reflect rough or blocky terrain as well as volume scattering; "
                    "it is not a unique ice signal. The image is in the Moon map "
                    "context and is never overlaid on Earth coordinates."
                ),
            }
        )
    rover_places = [
        item
        for item in place["observations"]
        if item.get("dataset_id") == "mars2020-rover-places-best-tactical"
    ]
    if rover_places:
        terrain_layer = next((item for item in layers if item["id"] == "terrain_dem"), None)
        aligned = bool(terrain_layer and terrain_layer.get("url") and place["body"] == "mars")
        layers.append(
            {
                "id": "rover_operations",
                "label": "Perseverance drive positions",
                "status": "available" if aligned else "metadata_only",
                "body": place["body"],
                "crs": "Mars equirectangular; planetocentric latitude, east-positive longitude",
                "alignment_group": terrain_layer.get("alignment_group")
                if terrain_layer and aligned
                else None,
                "url": f"/api/places/{place['id']}/layers/rover-operations.png"
                if aligned
                else None,
                "context_size_m": 20000.0,
                "observations": [
                    {
                        "id": item["id"],
                        "url": f"/api/places/{place['id']}/layers/rover-operations.png"
                        if aligned
                        else None,
                        "source_url": item.get("source_url"),
                        "acquired_at": item.get("acquired_at"),
                        "crs": (
                            "Mars equirectangular; planetocentric latitude, east-positive longitude"
                        ),
                    }
                    for item in rover_places
                ],
                "alignment_note": (
                    "Dots show discrete PDS best-tactical rover positions that fall "
                    "inside the local MOLA map window. The layer uses the same Mars "
                    "DEM grid; it does not connect dots or show the exact wheel "
                    "path, hazard decisions, or safe routes."
                ),
            }
        )
    return layers
