
import math
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic

# ---------------- PAGE CONFIG ----------------
st.set_page_config(
    page_title="Torpaq Sahəsi Analizi",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Torpaq Sahəsinin Ətraf Analizi")
st.caption("Azərbaycan üzrə torpaq sahəsinin ətrafındakı obyektləri araşdırın.")

st.info(
    "Məlumatlar Geoapify API və açıq xəritə məlumatlarına əsaslanır. "
    "Nəticələr rəsmi kadastr və ya mühəndislik ölçməsi deyil."
)

# ---------------- SETTINGS ----------------
API_URL = "https://api.geoapify.com/v2/places"
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"

try:
    API_KEY = "b8f6c459e6434e7582d251e5cf2de93e"
except Exception:
    API_KEY = "b8f6c459e6434e7582d251e5cf2de93e"

# Geoapify Places API kateqoriyaları
CATEGORY_MAP = {
    "Yollar": ["highway"],
    "Su obyektləri": ["waterway"],
    "Kəndlər və şəhərlər": ["populated_place"],
    "Məktəblər": ["education.school"],
    "Xəstəxana və klinikalar": ["healthcare"],
    "Mağazalar və marketlər": ["commercial"],
    "Yanacaqdoldurma məntəqələri": ["service.vehicle.fuel"],
    "Avtobus dayanacaqları": ["public_transport.bus"],
    "Hava limanları": ["airport"],
    "Yanğın və polis xidmətləri": [
        "service.fire_station",
        "service.police"
    ],
}

UNSUPPORTED_CATEGORIES = [
    "Elektrik infrastrukturu",
    "Dəmir yolu",
]

COLORS = {
    "Yollar": "blue",
    "Su obyektləri": "cadetblue",
    "Kəndlər və şəhərlər": "green",
    "Məktəblər": "purple",
    "Xəstəxana və klinikalar": "red",
    "Mağazalar və marketlər": "darkgreen",
    "Yanacaqdoldurma məntəqələri": "darkred",
    "Avtobus dayanacaqları": "lightblue",
    "Hava limanları": "pink",
    "Yanğın və polis xidmətləri": "gray",
}


# ---------------- GEOCODING ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def geocode_location(query, api_key):
    """Lokasiya adını koordinatlara çevirir."""

    response = requests.get(
        GEOCODE_URL,
        params={
            "text": query,
            "filter": "countrycode:az",
            "format": "json",
            "limit": 1,
            "apiKey": api_key,
        },
        timeout=(5, 20),
    )
    response.raise_for_status()

    data = response.json()
    results = data.get("results", [])

    if not results:
        return None

    item = results[0]

    return {
        "name": item.get("formatted", query),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }


# ---------------- DISTANCE ----------------
def distance_text(km):
    if km < 1:
        return f"{km * 1000:.0f} m"
    return f"{km:.2f} km"


# ---------------- PLACES API ----------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_places(lat, lon, radius_m, categories, api_key):
    """Seçilmiş kateqoriyaları bir API sorğusunda axtarır."""

    api_categories = []

    for category in categories:
        api_categories.extend(CATEGORY_MAP.get(category, []))

    api_categories = list(dict.fromkeys(api_categories))

    if not api_categories:
        return []

    response = requests.get(
        API_URL,
        params={
            "categories": ",".join(api_categories),
            "filter": f"circle:{lon},{lat},{radius_m}",
            "bias": f"proximity:{lon},{lat}",
            "limit": 500,
            "lang": "az",
            "apiKey": api_key,
        },
        timeout=(5, 30),
    )
    response.raise_for_status()

    data = response.json()
    return data.get("features", [])


# ---------------- ANALYSIS ----------------
def analyze_features(features, origin_lat, origin_lon, selected_categories):
    rows = []
    seen = set()

    for feature in features:
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry", {}) or {}
        coords = geometry.get("coordinates")

        if not coords or len(coords) < 2:
            if props.get("lat") is None or props.get("lon") is None:
                continue
            obj_lon = float(props["lon"])
            obj_lat = float(props["lat"])
        else:
            obj_lon = float(coords[0])
            obj_lat = float(coords[1])

        place_id = props.get("place_id") or (
            f"{obj_lat:.6f},{obj_lon:.6f},{props.get('name', '')}"
        )

        if place_id in seen:
            continue
        seen.add(place_id)

        api_cats = props.get("categories", [])
        if isinstance(api_cats, str):
            api_cats = [api_cats]

        matched_category = None

        for category in selected_categories:
            wanted = CATEGORY_MAP.get(category, [])

            if any(
                api_cat == wanted_cat
                or api_cat.startswith(wanted_cat + ".")
                for api_cat in api_cats
                for wanted_cat in wanted
            ):
                matched_category = category
                break

        # Bəzi API nəticələrində kateqoriya məlumatı fərqli ola bilər.
        # Belə halda kateqoriyanı əsas API kateqoriyasına görə müəyyən et.
        if matched_category is None:
            for category in selected_categories:
                wanted = CATEGORY_MAP.get(category, [])

                if any(
                    any(api_cat.startswith(w + ".") or api_cat == w
                        for w in wanted)
                    for api_cat in api_cats
                ):
                    matched_category = category
                    break

        if matched_category is None:
            continue

        km = geodesic(
            (origin_lat, origin_lon),
            (obj_lat, obj_lon)
        ).km

        name = (
            props.get("name")
            or props.get("address_line1")
            or props.get("formatted")
            or matched_category
        )

        rows.append({
            "Kateqoriya": matched_category,
            "Obyekt": name,
            "Məsafə (km)": round(km, 3),
            "Enlik": round(obj_lat, 6),
            "Uzunluq": round(obj_lon, 6),
            "Xəritə": (
                f"https://www.google.com/maps?q={obj_lat},{obj_lon}"
            ),
            "_lat": obj_lat,
            "_lon": obj_lon,
            "_id": str(place_id),
        })

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.sort_values("Məsafə (km)").reset_index(drop=True)

    return df


# ---------------- SIDEBAR ----------------
with st.sidebar:
    st.header("Axtarış parametrləri")

    location_query = st.text_input(
        "Torpaq sahəsinin lokasiyası",
        placeholder="Qəbələ, Azərbaycan"
    )

    radius_km = st.select_slider(
        "Axtarış radiusu",
        options=[1, 2, 3, 5, 7, 10],
        value=2,
        format_func=lambda x: f"{x} km"
    )

    selected_categories = st.multiselect(
        "Obyekt kateqoriyaları",
        options=list(CATEGORY_MAP.keys()),
        default=[
            "Yollar",
            "Məktəblər",
            "Su obyektləri",
            "Kəndlər və şəhərlər",
        ],
    )

    search_button = st.button(
        "🔎 Analiz et",
        type="primary",
        use_container_width=True,
    )

    st.caption("Nəticələr 30 dəqiqə keşlənir.")


# ---------------- SEARCH ----------------
if search_button:
    if not API_KEY:
        st.error(
            "Geoapify API açarı tapılmadı. "
            ".streamlit/secrets.toml faylını yaradın."
        )

    elif not location_query.strip():
        st.error("Lokasiya daxil edin.")

    elif not selected_categories:
        st.error("Ən azı bir kateqoriya seçin.")

    else:
        try:
            with st.spinner("Lokasiya axtarılır..."):
                location = geocode_location(
                    location_query.strip(),
                    API_KEY
                )

            if location is None:
                parts = [
                    p.strip() for p in location_query.split(",")
                ]

                location = None

                if len(parts) == 2:
                    try:
                        lat = float(parts[0])
                        lon = float(parts[1])

                        if 38 <= lat <= 42.5 and 44.5 <= lon <= 51:
                            location = {
                                "name": f"Koordinatlar: {lat}, {lon}",
                                "lat": lat,
                                "lon": lon,
                            }
                    except ValueError:
                        pass

            if location is None:
                st.error(
                    "Lokasiya tapılmadı. Şəhər, kənd və ya "
                    "40.4093, 49.8671 formatında koordinat daxil edin."
                )

            else:
                unsupported = [
                    c for c in UNSUPPORTED_CATEGORIES
                    if c in selected_categories
                ]

                with st.spinner("Ətraf obyektlər axtarılır..."):
                    features = fetch_places(
                        location["lat"],
                        location["lon"],
                        radius_km * 1000,
                        selected_categories,
                        API_KEY,
                    )

                results = analyze_features(
                    features,
                    location["lat"],
                    location["lon"],
                    selected_categories,
                )

                st.session_state["land_location"] = location
                st.session_state["land_radius"] = radius_km
                st.session_state["land_results"] = results
                st.session_state["land_unsupported"] = unsupported
                st.session_state["land_search_error"] = None

        except requests.HTTPError as exc:
            details = ""
            if exc.response is not None:
                details = exc.response.text[:500]

            st.session_state["land_search_error"] = (
                f"Geoapify HTTP xətası: {exc}. {details}"
            )

        except requests.RequestException as exc:
            st.session_state["land_search_error"] = (
                f"Geoapify serverinə qoşulmaq mümkün olmadı: {exc}"
            )

        except Exception as exc:
            st.session_state["land_search_error"] = str(exc)


# ---------------- RESULTS ----------------
if st.session_state.get("land_search_error"):
    st.error(st.session_state["land_search_error"])

if (
    "land_location" in st.session_state
    and "land_results" in st.session_state
):
    location = st.session_state["land_location"]
    results = st.session_state["land_results"]
    radius_used = st.session_state["land_radius"]

    st.subheader("📍 Analiz edilən lokasiya")
    st.write(location["name"])

    st.caption(
        f"Koordinatlar: {location['lat']:.6f}, "
        f"{location['lon']:.6f} | Radius: {radius_used} km"
    )

    unsupported = st.session_state.get("land_unsupported", [])

    if unsupported:
        st.warning(
            "Bu API versiyasında dəstəklənməyən kateqoriyalar "
            "nəticələrə daxil edilməyib: "
            + ", ".join(unsupported)
            + "."
        )

    if results.empty:
        st.warning(
            "Bu radiusda seçilmiş kateqoriyalar üzrə nəticə tapılmadı. "
            "Başqa kateqoriya və ya daha böyük radius sınayın."
        )

    else:
        c1, c2, c3 = st.columns(3)

        c1.metric("Tapılan obyektlər", len(results))
        c2.metric(
            "Kateqoriyalar",
            results["Kateqoriya"].nunique()
        )
        c3.metric(
            "Ən yaxın obyekt",
            distance_text(float(results.iloc[0]["Məsafə (km)"]))
        )

        st.subheader("⭐ Kateqoriyalar üzrə ən yaxın obyekt")

        nearest = (
            results.sort_values("Məsafə (km)")
            .groupby("Kateqoriya", as_index=False)
            .first()
        )

        nearest_display = nearest[
            ["Kateqoriya", "Obyekt", "Məsafə (km)", "Xəritə"]
        ].copy()

        nearest_display["Məsafə"] = (
            nearest_display["Məsafə (km)"].apply(distance_text)
        )

        st.dataframe(
            nearest_display[
                ["Kateqoriya", "Obyekt", "Məsafə", "Xəritə"]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Xəritə": st.column_config.LinkColumn(
                    "Xəritədə aç",
                    display_text="Google Maps"
                )
            }
        )

        st.subheader("🗺️ Xəritə")

        map_object = folium.Map(
            location=[location["lat"], location["lon"]],
            zoom_start=13,
            control_scale=True,
        )

        folium.Marker(
            [location["lat"], location["lon"]],
            tooltip="Torpaq sahəsinin lokasiyası",
            popup=location["name"],
            icon=folium.Icon(color="red", icon="home"),
        ).add_to(map_object)

        folium.Circle(
            location=[location["lat"], location["lon"]],
            radius=radius_used * 1000,
            color="blue",
            fill=True,
            fill_opacity=0.06,
        ).add_to(map_object)

        for _, row in results.head(500).iterrows():
            folium.CircleMarker(
                location=[row["_lat"], row["_lon"]],
                radius=5,
                color=COLORS.get(row["Kateqoriya"], "blue"),
                fill=True,
                fill_opacity=0.8,
                tooltip=(
                    f"{row['Obyekt']} — "
                    f"{distance_text(float(row['Məsafə (km)']))}"
                ),
                popup=folium.Popup(
                    f"<b>{row['Obyekt']}</b><br>"
                    f"Kateqoriya: {row['Kateqoriya']}<br>"
                    f"Məsafə: {distance_text(float(row['Məsafə (km)']))}<br>"
                    f"<a href='{row['Xəritə']}' target='_blank'>Xəritədə aç</a>",
                    max_width=300,
                ),
            ).add_to(map_object)

        st_folium(
            map_object,
            use_container_width=True,
            height=560,
            returned_objects=[],
        )

        st.subheader("📋 Bütün nəticələr")

        category_filter = st.selectbox(
            "Kateqoriya üzrə filtr",
            ["Hamısı"] + sorted(results["Kateqoriya"].unique())
        )

        filtered = (
            results if category_filter == "Hamısı"
            else results[results["Kateqoriya"] == category_filter]
        )

        table = filtered[
            ["Kateqoriya", "Obyekt", "Məsafə (km)",
             "Enlik", "Uzunluq", "Xəritə"]
        ].copy()

        table["Məsafə"] = table["Məsafə (km)"].apply(distance_text)

        st.dataframe(
            table[
                ["Kateqoriya", "Obyekt", "Məsafə",
                 "Enlik", "Uzunluq", "Xəritə"]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Xəritə": st.column_config.LinkColumn(
                    "Xəritə linki",
                    display_text="Aç"
                )
            },
        )

        csv_data = filtered.drop(
            columns=["_lat", "_lon", "_id"],
            errors="ignore",
        ).to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            "⬇️ Nəticələri CSV kimi yüklə",
            data=csv_data,
            file_name="torpaq_etraf_analizi.csv",
            mime="text/csv",
        )

        st.caption(
            "Məsafələr düzxətli geodezik məsafələrdir; "
            "avtomobil yolu ilə məsafə deyil. "
            "Xəritədə yalnız ilk 500 nəticə göstərilir."
        )

else:
    st.markdown("### Necə istifadə etməli?")
    st.markdown(
        "1. Lokasiya və ya koordinat daxil edin.\n"
        "2. 1–10 km radius seçin.\n"
        "3. Kateqoriyaları seçin.\n"
        "4. **Analiz et** düyməsinə basın.\n"
        "5. Nəticələri xəritədə və cədvəldə yoxlayın."
    )

st.caption(
    "Məkan məlumatları üçün Geoapify və "
    "© OpenStreetMap contributors mənbələrini qeyd edin."
)
