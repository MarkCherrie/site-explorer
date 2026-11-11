# Renewable generation site explorer

Pick an area in Europe and see it in 3D: sea depths and land heights as animated contours, with wind turbines, a water layer and the live wind forecast.

**Open it:** https://<user>.github.io/<repo>/

## Data
- Sea depths: [EMODnet Bathymetry](https://emodnet.ec.europa.eu/en/bathymetry)
- Land heights: SRTM via [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/)
- Offshore turbines: [DeepOWT](https://zenodo.org/records/23160399) (CC-BY-4.0)
- UK turbines: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL)
- Wind: [Open-Meteo](https://open-meteo.com/) forecast and ERA5 archive (CC-BY-4.0)
- Search: Nominatim / OpenStreetMap

`tools/` holds the scripts that build the two turbine files in `data/`.
