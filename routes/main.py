from flask import Blueprint, render_template
import geopandas as gpd
import pandas as pd
import folium
import os
import unicodedata
from branca.colormap import LinearColormap

main_bp = Blueprint("main", __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
GJSON_REGIONES = os.path.join(DATA_DIR, "regiones_cr.geojson")
EXCEL_INFO = os.path.join(DATA_DIR, "info.xlsx")


def _norm(s: str) -> str:
    """Mayúsculas, sin tildes, sin espacios extra."""
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


@main_bp.route("/")
def mapa():
    # --- 1) Regiones (solo columnas útiles, CRS WGS84) ---
    gdf = gpd.read_file(GJSON_REGIONES)
    gdf = gdf[["geometry", "nomb_uger"]].rename(columns={"nomb_uger": "REGION"})
    if gdf.crs is None or gdf.crs.to_string().lower() != "epsg:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # Campo auxiliar normalizado para el join
    gdf["REGION_NORM"] = gdf["REGION"].apply(_norm)

    # --- 2) Totales desde Excel (hoja con columnas: Región, Total) ---
    # Si el archivo tiene una sola hoja, se toma esa; si tiene varias, toma la primera.
    hojas = pd.read_excel(EXCEL_INFO, sheet_name=None)
    df_info = next(iter(hojas.values()))
    df_info = df_info.rename(columns=lambda c: str(c).strip())
    df_info = df_info[["Región", "Total"]]
    df_info["REGION_NORM"] = df_info["Región"].apply(_norm)
    df_info["Total"] = (
        pd.to_numeric(df_info["Total"], errors="coerce").fillna(0).astype(int)
    )

    # --- 3) Emparejar regiones ↔ totales ---
    gdf = gdf.merge(df_info[["REGION_NORM", "Total"]], on="REGION_NORM", how="left")
    gdf["Total"] = gdf["Total"].fillna(0).astype(int)

    # --- 3.5) Cargar Sedes y Acreditaciones desde Excel ---
    # Cargar hojas específicas de sedes y acreditaciones
    df_sedes = pd.read_excel(EXCEL_INFO, sheet_name="sedes")
    df_acreditaciones = pd.read_excel(EXCEL_INFO, sheet_name="acreditaciones")

    # --- 4) Mapa base ---
    m = folium.Map(location=[9.7489, -83.7534], zoom_start=8, tiles="cartodbpositron")

    # --- 4.5) Agregar Sedes al mapa ---
    fg_sedes = folium.FeatureGroup(name="Sedes", show=True).add_to(m)

    for _, sede in df_sedes.iterrows():
        folium.Marker(
            location=[sede["LATITUD"], sede["LONGITUD"]],
            popup=f"<b>SEDE:</b><br>{sede['SEDE']}",
            tooltip=sede["SEDE"],
            icon=folium.Icon(color="blue", icon="graduation-cap", prefix="fa"),
        ).add_to(fg_sedes)

    # --- 4.6) Agregar Acreditaciones al mapa ---
    fg_acreditaciones = folium.FeatureGroup(name="Acreditaciones", show=True).add_to(m)

    for _, acred in df_acreditaciones.iterrows():
        folium.Marker(
            location=[acred["LATITUD"], acred["LONGITUD"]],
            popup=f"<b>ACREDITACIÓN:</b><br>{acred['ACREDITACIONES']}",
            tooltip=acred["ACREDITACIONES"],
            icon=folium.Icon(color="green", icon="certificate", prefix="fa"),
        ).add_to(fg_acreditaciones)

    # --- 5) Capa coloreada por Total ---
    fg_total = folium.FeatureGroup(name="Regiones – Total", show=True).add_to(m)

    # Más divisiones de color usando rangos lineales (8 divisiones)
    serie = gdf["Total"]
    min_val = int(serie.min())
    max_val = int(serie.max())

    if (max_val - min_val) == 0:
        # Si todos los valores son iguales, crear rangos artificiales
        bins = list(range(min_val, min_val + 9))
    else:
        # Crear 8 divisiones lineales entre min y max
        step = (max_val - min_val) / 7  # 7 pasos para 8 rangos
        bins = [min_val + int(i * step) for i in range(8)]
        bins[-1] = max_val  # Asegurar que el último bin sea exactamente el máximo

    # Paleta con colores muy contrastantes para mejor diferenciación
    cmap = LinearColormap(
        colors=[
            "#ffffcc",
            "#ffeda0",
            "#fed976",
            "#feb24c",
            "#fd8d3c",
            "#fc4e2a",
            "#e31a1c",
            "#bd0026",
        ],
        vmin=min_val,
        vmax=max_val,
    )
    cmap.caption = "Total por región"

    # Pintar cada polígono según su Total
    def _style(feature, s=cmap):
        v = feature["properties"].get("Total", 0)
        return {"fillColor": s(v), "color": "gray", "weight": 0.8, "fillOpacity": 0.65}

    folium.GeoJson(
        gdf[["geometry", "REGION", "Total"]],
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(
            fields=["REGION", "Total"], aliases=["Región:", "Total:"], localize=True
        ),
        name="Choropleth Total",
    ).add_to(fg_total)

    cmap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    return render_template("index.html", mapa=m.get_root().render())
