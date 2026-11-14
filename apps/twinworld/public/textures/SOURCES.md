# Planetary globe texture sources

These local JPEGs are presentation textures loaded by `PlanetaryGlobe`. They
are not inputs to the indexed Earth–Mars image patches, DINOv2 embeddings,
retrieval rankings, terrain scorecards, or API responses. The source images are
reprojected/resampled to equirectangular textures for rendering.

| File | Source and product | Source scale | Processing | Attribution |
| --- | --- | --- | --- | --- |
| `earth.jpg` | NASA Earth Observatory, Blue Marble: Next Generation, January 2004 global composite. [Product page](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-map/) | The downloaded 21,600 × 10,800 global JPEG is listed at 2 km/pixel; the higher-resolution source is published as 500 m/pixel regional tiles. | Resized to 4,096 × 2,048 for the globe. | NASA Earth Observatory / Blue Marble: Next Generation. NASA does not endorse ENOM. |
| `mars.jpg` | NASA Solar System Treks WMTS, Mars Viking MDIM 2.1 colorized global mosaic. [Layer capabilities](https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml) · [USGS product metadata](https://astrogeology.usgs.gov/search/map/mars_viking_colorized_global_mosaic_232m) | 232 m/pixel at the equator (underlying global mosaic). | NASA Trek equirectangular WMTS zoom 4 tiles assembled row-major and resized to 4,096 × 2,048. | NASA Ames Viking Orbiter imagery; USGS Astrogeology MDIM 2.1; NASA/JPL Solar System Treks. NASA does not endorse ENOM. |
| `moon.jpg` | NASA Solar System Treks WMTS, LRO LROC WAC Global Mosaic v2. [Layer capabilities](https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml) · [PDS product details](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_GLOBAL/) | 303 pixels/degree (approximately 100 m/pixel near the equator). | NASA Trek equirectangular WMTS zoom 3 tiles assembled row-major to 4,096 × 2,048; monochrome source. | NASA LRO / LROC team. NASA does not endorse ENOM. |

NASA and partner data are used for informational and research visualization.
The texture files do not represent current conditions or analysis-ready source
observations. Refer to the linked product records for complete source and use
information.

At higher zoom, the Earth globe requests NASA GIBS `BlueMarble_NextGeneration`
tiles (August 2004, 500 m/pixel). This is a cloud-free global composite and is
used as a complete surface overlay; it is not a current-date weather image.
