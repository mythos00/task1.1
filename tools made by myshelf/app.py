import math
import time
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# -------------------- PAGE CONFIG --------------------
st.set_page_config(
    page_title="Torpaq Sahəsi Analizi",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Torpaq Sahəsinin Ətraf Analizi")
st.caption(
    "Azərbaycan üzrə torpaq lokasiyasını axtarın və ətrafdakı yolları, "
    "su obyektlərini, yaşayış məntəqələrini və digər infrastrukturu araşdırın."
)

st.info(
    "Məlumatlar OpenStreetMap könüllülərinin xəritəyə əlavə etdiyi obyektlərə əsaslanır. "
    "Xəritədə olmayan obyekt tapılmaya bilər. Nəticələr rəsmi kadastr və ya mühəndislik "
    "ölçməsi hesab edilmir."
)

# -------------------- CONSTANTS --------------------
HEADERS = {
    "User-Agent": "AzerbaijanLandProximityApp/1.0 (Streamlit educational project)"
}

CATEGORIES = {
    "Yollar": (
        'way["highway"](around:{radius},{lat},{lon});'
    ),
    "Su obyektləri": (
        'way["waterway"](around:{radius},{lat},{lon});'
        'relation["waterway"](around:{radius},{lat},{lon});'
        'way["natural"~"water|wetland"](around:{radius},{lat},{lon});'
        'relation["natural"~"water|wetland"](around:{radius},{lat},{lon});'
        'way["water"~"."](around:{radius},{lat},{lon});'
        'relation["water"~"."](around:{radius},{lat},{lon});'
    ),
    "Kəndlər və şəhərlər": (
        'node["place"~"city|town|village|hamlet|suburb"](around:{radius},{lat},{lon});'
        'way["place"~"city|town|village|hamlet"](around:{radius},{lat},{lon});'
        'relation["place"~"city|town|village|hamlet"](around:{radius},{lat},{lon});'
    ),
    "Elektrik infrastrukturu": (
        'node["power"~"line|minor_line|substation|plant|tower|pole"](around:{radius},{lat},{lon});'
        'way["power"~"line|minor_line|substation|plant|cable"](around:{radius},{lat},{lon});'
        'relation["power"~"line|minor_line|substation|plant|cable"](around:{radius},{lat},{lon});'
    ),
    "Məktəblər": (
        'node["amenity"="school"](around:{radius},{lat},{lon});'
        'way["amenity"="school"](around:{radius},{lat},{lon});'
        'relation["amenity"="school"](around:{radius},{lat},{lon});'
    ),
    "Xəstəxana və klinikalar": (
        'node["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});'
        'way["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});'
        'relation["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});'
    ),
    "Mağazalar və marketlər": (
        'node["shop"](around:{radius},{lat},{lon});'
        'way["shop"](around:{radius},{lat},{lon});'
        'relation["shop"](around:{radius},{lat},{lon});'
    ),
    "Yanacaqdoldurma məntəqələri": (
        'node["amenity"="fuel"](around:{radius},{lat},{lon});'
        'way["amenity"="fuel"](around:{radius},{lat},{lon});'
        'relation["amenity"="fuel"](around:{radius},{lat},{lon});'
    ),
    "Dəmir yolu": (
        'way["railway"~"rail|light_rail|narrow_gauge"](around:{radius},{lat},{lon});'
        'relation["railway"~"rail|light_rail|narrow_gauge"](around:{radius},{lat},{lon});'
    ),
    "Avtobus dayanacaqları": (
        'node["highway"="bus_stop"](around:{radius},{lat},{lon});'
        'node["public_transport"="platform"](around:{radius},{lat},{lon});'
    ),
    "Hava limanları": (
        'node["aeroway"="aerodrome"](around:{radius},{lat},{lon});'
        'way["aeroway"="aerodrome"](around:{radius},{lat},{lon});'
        'relation["aeroway"="aerodrome"](around:{radius},{lat},{lon});'
    ),
    "Yanğın və polis xidmətləri": (
        'node["amenity"~"fire_station|police"](around:{radius},{lat},{lon});'
        'way["amenity"~"fire_station|police"](around:{radius},{lat},{lon});'
        'relation["amenity"~"fire_station|police"](around:{radius},{lat},{lon});'
    ),
}

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# -------------------- HELPERS --------------------
def geocode_location(query: str):
    """Place name/address -> coordinates using Nominatim."""
    geolocator = Nominatim(
        user_agent="AzerbaijanLandProximityApp/1.0",
        timeout=15
    )
    result = geolocator.geocode(
        query,
        country_codes="az",
        exactly_one=True,
        addressdetails=True
    )
    if not result:
        return None

    return {
        "name": result.address,
        "lat": float(result.latitude),
        "lon": float(result.longitude),
    }


def get_element_coordinates(element):
    """Return a representative coordinate for an OSM node/way/relation."""
    if element.get("type") == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)

    center = element.get("center")
    if center and center.get("lat") is not None and center.get("lon") is not None:
        return float(center["lat"]), float(center["lon"])

    geometry = element.get("geometry")
    if geometry:
        points = [
            (p.get("lat"), p.get("lon"))
            for p in geometry
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        if points:
            # Representative point: average of the geometry coordinates.
            return (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            )
    return None


def readable_name(tags, category, element_type, element_id):
    name = tags.get("name") or tags.get("name:az") or tags.get("official_name")
    if name:
        return name
    if category == "Yollar":
        return tags.get("highway", "Adsız yol")
    if category == "Su obyektləri":
        return tags.get("waterway") or tags.get("water") or tags.get("natural") or "Adsız su obyekti"
    if category == "Elektrik infrastrukturu":
        return tags.get("power", "Elektrik infrastrukturu")
    return f"Adsız obyekt ({element_type}/{element_id})"



@st.cache_data(ttl=1800, show_spinner=False)
def overpass_query(lat, lon, radius_m, category_names):
    """Kateqoriyaları bir sorğuda axtarır və nəticəni 30 dəqiqə keşləyir."""

    clauses = []

    for category in category_names:
        template = CATEGORIES.get(category)
        if not template:
            continue

        clauses.append(
            template.format(
                radius=int(radius_m),
                lat=float(lat),
                lon=float(lon)
            )
        )

    if not clauses:
        return []

    query = (
        "[out:json][timeout:45];\n"
        "(\n" + "\n".join(clauses) + "\n"
        ");\n"
        "out center;"
    )

    errors = []

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=HEADERS,
                timeout=(5, 55)
            )

            response.raise_for_status()
            data = response.json()

            return data.get("elements", [])

        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{endpoint}: {exc}")

    raise RuntimeError(
        "Overpass serverləri cavab vermədi. "
        "Radiusu kiçildin və bir qədər sonra yenidən yoxlayın. "
        + " | ".join(errors)
    )



def analyze_elements(elements, origin_lat, origin_lon, selected_categories):
    rows = []
    seen = set()

    for element in elements:
        element_type = element.get("type", "unknown")
        element_id = element.get("id", "")
        unique_id = (element_type, element_id)
        if unique_id in seen:
            continue
        seen.add(unique_id)

        tags = element.get("tags", {}) or {}
        coords = get_element_coordinates(element)
        if not coords:
            continue

        obj_lat, obj_lon = coords
        distance_km = geodesic(
            (origin_lat, origin_lon),
            (obj_lat, obj_lon)
        ).km

        matched_category = None
        for category in selected_categories:
            if category == "Yollar" and "highway" in tags:
                matched_category = category
                break
            if category == "Su obyektləri" and (
                "waterway" in tags or "water" in tags or tags.get("natural") in {"water", "wetland"}
            ):
                matched_category = category
                break
            if category == "Kəndlər və şəhərlər" and "place" in tags:
                matched_category = category
                break
            if category == "Elektrik infrastrukturu" and "power" in tags:
                matched_category = category
                break
            if category == "Məktəblər" and tags.get("amenity") == "school":
                matched_category = category
                break
            if category == "Xəstəxana və klinikalar" and tags.get("amenity") in {"hospital", "clinic", "doctors"}:
                matched_category = category
                break
            if category == "Mağazalar və marketlər" and "shop" in tags:
                matched_category = category
                break
            if category == "Yanacaqdoldurma məntəqələri" and tags.get("amenity") == "fuel":
                matched_category = category
                break
            if category == "Dəmir yolu" and "railway" in tags:
                matched_category = category
                break
            if category == "Avtobus dayanacaqları" and (
                tags.get("highway") == "bus_stop" or tags.get("public_transport") == "platform"
            ):
                matched_category = category
                break
            if category == "Hava limanları" and tags.get("aeroway") == "aerodrome":
                matched_category = category
                break
            if category == "Yanğın və polis xidmətləri" and tags.get("amenity") in {"fire_station", "police"}:
                matched_category = category
                break

        if matched_category is None:
            continue

        rows.append({
            "Kateqoriya": matched_category,
            "Obyekt": readable_name(tags, matched_category, element_type, element_id),
            "Məsafə (km)": round(distance_km, 3),
            "Enlik": round(obj_lat, 6),
            "Uzunluq": round(obj_lon, 6),
            "OSM": f"https://www.openstreetmap.org/{element_type}/{element_id}",
            "_lat": obj_lat,
            "_lon": obj_lon,
            "_id": f"{element_type}/{element_id}",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Məsafə (km)").reset_index(drop=True)
    return df


def distance_text(km):
    if km < 1:
        return f"{km * 1000:.0f} m"
    return f"{km:.2f} km"


# -------------------- SIDEBAR --------------------
with st.sidebar:
    st.header("Axtarış parametrləri")
    location_query = st.text_input(
        "Torpaq sahəsinin lokasiyası",
        placeholder="Məsələn: Qəbələ, Azərbaycan"
    )
    radius_km = st.select_slider(
        "Axtarış radiusu",
        options=[1, 2, 5, 10, 15, 20, 30, 50],
        value=2,
        format_func=lambda x: f"{x} km"
    )
    selected_categories = st.multiselect(
        "Axtarılacaq obyektlər",
        options=list(CATEGORIES.keys()),
        default=["Yollar", "Su obyektləri", "Kəndlər və şəhərlər", "Elektrik infrastrukturu"]
    )
    search_button = st.button("🔎 Analiz et", type="primary", use_container_width=True)
    st.caption("Qeyd: böyük radius və çoxlu kateqoriya sorğunu ləngidə bilər.")

# -------------------- SEARCH --------------------
if search_button:
    if not location_query.strip():
        st.error("Zəhmət olmasa, torpaq sahəsinin lokasiyasını daxil edin.")
    elif not selected_categories:
        st.error("Ən azı bir obyekt kateqoriyası seçin.")
    else:
        with st.spinner("Lokasiya tapılır..."):
            try:
                location = geocode_location(location_query.strip())
            except Exception as exc:
                location = None
                st.error(f"Lokasiyanı axtararkən xəta baş verdi: {exc}")

        if location is None:
            st.warning(
                "Lokasiya tapılmadı. Şəhər, kənd və ya ünvan adını Azərbaycan daxilində "
                "daha dəqiq yazın. Koordinatla axtarış da mümkündür: məsələn, 40.4093, 49.8671."
            )
            # Support direct coordinates as fallback.
            try:
                parts = [p.strip() for p in location_query.split(",")]
                if len(parts) == 2:
                    lat_value, lon_value = float(parts[0]), float(parts[1])
                    if 38.0 <= lat_value <= 42.5 and 44.5 <= lon_value <= 51.0:
                        location = {
                            "name": f"Koordinatlar: {lat_value}, {lon_value}",
                            "lat": lat_value,
                            "lon": lon_value,
                        }
            except ValueError:
                pass

        if location:
            st.session_state["land_location"] = location
            st.session_state["land_radius"] = radius_km
            st.session_state["land_categories"] = selected_categories
            st.session_state.pop("land_results", None)

            with st.spinner(
                f"{radius_km} km radiusda obyektlər axtarılır. Bu, serverdən asılı olaraq vaxt apara bilər..."
            ):
                try:
                    raw_elements = overpass_query(
                        location["lat"],
                        location["lon"],
                        radius_km * 1000,
                        selected_categories
                    )
                    results = analyze_elements(
                        raw_elements,
                        location["lat"],
                        location["lon"],
                        selected_categories
                    )
                    st.session_state["land_results"] = results
                    st.session_state["land_raw_count"] = len(raw_elements)
                    st.session_state["land_search_error"] = None
                except Exception as exc:
                    st.session_state["land_search_error"] = str(exc)

# -------------------- RESULTS --------------------
if st.session_state.get("land_search_error"):
    st.error(st.session_state["land_search_error"])
    st.caption("İctimai Overpass serverləri bəzən yüklənmiş olur. Daha kiçik radius seçib sonra yenidən yoxlayın.")

if "land_location" in st.session_state and "land_results" in st.session_state:
    location = st.session_state["land_location"]
    results = st.session_state["land_results"]
    radius_used = st.session_state["land_radius"]

    st.subheader("📍 Analiz edilən lokasiya")
    st.write(location["name"])
    st.caption(f"Koordinatlar: {location['lat']:.6f}, {location['lon']:.6f} | Radius: {radius_used} km")

    if results.empty:
        st.warning(
            "Seçilmiş radiusda seçilən kateqoriyalar üzrə xəritələnmiş obyekt tapılmadı. "
            "Daha böyük radiusla və ya başqa kateqoriyalarla yoxlayın."
        )
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Tapılan obyektlər", len(results))
        c2.metric("Kateqoriyalar", results["Kateqoriya"].nunique())
        c3.metric("Ən yaxın obyekt", distance_text(float(results.iloc[0]["Məsafə (km)"])))

        st.subheader("⭐ Hər kateqoriya üzrə ən yaxın obyekt")
        nearest = (
            results.sort_values("Məsafə (km)")
            .groupby("Kateqoriya", as_index=False)
            .first()
            .sort_values("Məsafə (km)")
        )
        nearest_display = nearest[["Kateqoriya", "Obyekt", "Məsafə (km)", "OSM"]].copy()
        nearest_display["Məsafə"] = nearest_display["Məsafə (km)"].apply(distance_text)
        st.dataframe(
            nearest_display[["Kateqoriya", "Obyekt", "Məsafə", "OSM"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "OSM": st.column_config.LinkColumn("Xəritədə aç", display_text="OpenStreetMap")
            }
        )

        st.subheader("🗺️ Xəritə")
        map_object = folium.Map(
            location=[location["lat"], location["lon"]],
            zoom_start=12,
            control_scale=True
        )
        folium.Marker(
            [location["lat"], location["lon"]],
            tooltip="Torpaq sahəsinin lokasiyası",
            popup=f"<b>Torpaq sahəsi</b><br>{location['name']}",
            icon=folium.Icon(color="red", icon="home")
        ).add_to(map_object)

        # Radius circle is a straight-line search boundary, not a driving distance.
        folium.Circle(
            location=[location["lat"], location["lon"]],
            radius=radius_used * 1000,
            color="blue",
            fill=True,
            fill_opacity=0.06,
            tooltip=f"{radius_used} km axtarış radiusu"
        ).add_to(map_object)

        color_by_category = {
            "Yollar": "blue",
            "Su obyektləri": "cadetblue",
            "Kəndlər və şəhərlər": "green",
            "Elektrik infrastrukturu": "orange",
            "Məktəblər": "purple",
            "Xəstəxana və klinikalar": "red",
            "Mağazalar və marketlər": "darkgreen",
            "Yanacaqdoldurma məntəqələri": "darkred",
            "Dəmir yolu": "black",
            "Avtobus dayanacaqları": "lightblue",
            "Hava limanları": "pink",
            "Yanğın və polis xidmətləri": "gray",
        }

        # Plot a manageable number of closest results for browser performance.
        for _, row in results.head(500).iterrows():
            color = color_by_category.get(row["Kateqoriya"], "blue")
            popup_html = (
                f"<b>{row['Obyekt']}</b><br>"
                f"Kateqoriya: {row['Kateqoriya']}<br>"
                f"Məsafə: {distance_text(float(row['Məsafə (km)']))}<br>"
                f"<a href='{row['OSM']}' target='_blank'>OpenStreetMap-də aç</a>"
            )
            folium.CircleMarker(
                location=[row["_lat"], row["_lon"]],
                radius=5,
                color=color,
                fill=True,
                fill_opacity=0.8,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{row['Obyekt']} — {distance_text(float(row['Məsafə (km)']))}"
            ).add_to(map_object)

        st_folium(map_object, use_container_width=True, height=560, returned_objects=[])

        st.subheader("📋 Bütün nəticələr")
        category_filter = st.selectbox(
            "Kateqoriya üzrə filtr",
            options=["Hamısı"] + sorted(results["Kateqoriya"].unique().tolist())
        )
        filtered = results if category_filter == "Hamısı" else results[results["Kateqoriya"] == category_filter]
        table = filtered[["Kateqoriya", "Obyekt", "Məsafə (km)", "Enlik", "Uzunluq", "OSM"]].copy()
        table["Məsafə"] = table["Məsafə (km)"].apply(distance_text)
        st.dataframe(
            table[["Kateqoriya", "Obyekt", "Məsafə", "Enlik", "Uzunluq", "OSM"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "OSM": st.column_config.LinkColumn("Xəritə linki", display_text="Aç")
            }
        )

        csv_data = filtered.drop(columns=["_lat", "_lon", "_id"], errors="ignore").to_csv(
            index=False
        ).encode("utf-8-sig")
        st.download_button(
            "⬇️ Nəticələri CSV kimi yüklə",
            data=csv_data,
            file_name="torpaq_etraf_analizi.csv",
            mime="text/csv"
        )

        st.caption(
            "Məsafələr torpaq lokasiyasından obyektin xəritədəki təmsilçi nöqtəsinə qədər "
            "geodezik düzxətli məsafədir; avtomobil yolu məsafəsi deyil. Xətt və sahə obyektləri "
            "üçün göstərilən nöqtə obyektin təxmini mərkəzidir."
        )

else:
    st.markdown("### Necə istifadə etməli?")        
    st.markdown(
        "1. Soldakı sahəyə şəhər, kənd, ünvan və ya koordinat daxil edin.\n"
        "2. Axtarış radiusunu seçin.\n"
        "3. Lazım olan obyekt kateqoriyalarını seçin.\n"
        "4. **Analiz et** düyməsinə basın.\n"
        "5. Ən yaxın obyektləri, məsafələri, xəritəni və CSV ixracını yoxlayın."
    )
    st.markdown("Nümunə lokasiyalar: `Qəbələ, Azərbaycan`, `Şamaxı, Azərbaycan`, `40.4093, 49.8671`.")
    st.success("SƏHİFƏ YÜKLƏNDİ")