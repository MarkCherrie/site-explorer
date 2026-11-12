# Site explorer

Pick an area in Europe and explore it in 3D: sea depths and land heights as animated contours, with
optional surfaces, water, rivers, hills, turbines, wind, waves, sun and shadows, buildings, people,
the power network and live ships.

**Open it:** https://markcherrie.github.io/site-explorer/

## Tours
- **Topography:** contours, terraced relief, water, hill names.
- **Wind energy:** relief, turbines, a side-on view of the wind, a yield estimate, the forecast loop.
- **Solar:** relief, sun and shadows with a sunlight summary, days at midsummer and midwinter.
- **Persistence (weather windows):** waves, live ships, offshore access windows for the next 48 hours
  and how often they open through the year.
- **Substation headroom (Currie, SPEN; Kirkwall, SSEN):** the site and its network data, a baseline
  hourly model of demand and generation for 2025, and headroom against firm and reverse power capacity.

## Data
- Sea depths: [EMODnet Bathymetry](https://emodnet.ec.europa.eu/en/bathymetry)
- Land heights: SRTM via [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/)
- Offshore turbines: [DeepOWT](https://zenodo.org/records/23160399) (CC BY 4.0)
- UK turbines, buildings, roads, rivers and the power network: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL); buildings and map tiles via [OpenFreeMap](https://openfreemap.org)
- Weather, waves and sunlight: [Open-Meteo](https://open-meteo.com/) forecast and ERA5 archive (CC BY 4.0)
- Population: GHSL 2025, European Commission JRC (CC BY 4.0)
- Hills: [Database of British and Irish Hills](https://www.hills-database.co.uk) v18.6 (CC BY 4.0)
- Deprivation: SIMD 2020v2, Scottish Government (OGL)
- Substations: SP Energy Networks and SSEN Distribution open data (CC BY 4.0)
- Live ships: [aisstream.io](https://aisstream.io), through a relay (see `tools/ais-relay/`)
- Search: Nominatim / OpenStreetMap

`tools/` holds the scripts that build the files in `data/`, and the ship relay.
