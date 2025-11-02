# app.py
# Single Site Plan v2 — Streamlit + ezdxf (DXF in metres) + PDF render
# BILINGUAL UI (English above Kannada). PDF/DXF output in English only.

import io
import math
import textwrap
import tempfile
import requests
import os
from PIL import Image, ImageDraw
import streamlit as st
import ezdxf
from ezdxf.math import Vec2
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt

# ----------------- Helpers: OSM tiles / keyplan -----------------
def latlon_to_tile_xy(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile

def fetch_tile_image(z, x, y, scale=2):
    # use @2x tiles if available
    if scale == 2:
        url = f"https://tile.openstreetmap.org/{z}/{x}/{y}@2x.png"
    else:
        url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    headers = {"User-Agent": "SingleSitePlan/1.0"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        # fallback gray tile
        size = 256 * (2 if scale == 2 else 1)
        return Image.new("RGBA", (size, size), (240,240,240,255))

def make_keyplan_image(lat, lon, zoom=16, radius_m=200, tiles_radius=1, scale=2):
    xtile_f, ytile_f = latlon_to_tile_xy(lat, lon, zoom)
    x_center = int(math.floor(xtile_f)); y_center = int(math.floor(ytile_f))
    tile_px = 256 * (2 if scale == 2 else 1)
    cols = 2 * tiles_radius + 1
    stitched = Image.new("RGBA", (cols * tile_px, cols * tile_px))
    for dy in range(-tiles_radius, tiles_radius + 1):
        for dx in range(-tiles_radius, tiles_radius + 1):
            img = fetch_tile_image(zoom, x_center + dx, y_center + dy, scale=scale)
            stitched.paste(img, ((dx + tiles_radius) * tile_px, (dy + tiles_radius) * tile_px))
    frac_x = (xtile_f - x_center); frac_y = (ytile_f - y_center)
    center_px = (tiles_radius * tile_px + int(frac_x * tile_px), tiles_radius * tile_px + int(frac_y * tile_px))
    R = 6378137.0
    mpp = (math.cos(math.radians(lat)) * 2 * math.pi * R) / (tile_px * (2**zoom))
    radius_px = max(4, int(radius_m / mpp))
    draw = ImageDraw.Draw(stitched)
    bbox = [center_px[0] - radius_px, center_px[1] - radius_px, center_px[0] + radius_px, center_px[1] + radius_px]
    draw.ellipse(bbox, outline=(200,0,0,255), width=6)
    draw.ellipse([center_px[0]-3, center_px[1]-3, center_px[0]+3, center_px[1]+3], fill=(0,0,0,255))
    return stitched

# ----------------- Streamlit UI -----------------
st.set_page_config(page_title="Single Site Plan — DXF + PDF", layout="centered")
st.title("Single Site Plan — DXF + PDF (A3)")

st.markdown("Fill the form (English on top, Kannada below). Output files will be in English only.")

# --- Site details (bilingual: English then Kannada) ---
st.subheader("Site details / ಸೈಟ್ ವಿವರಗಳು")
survey_no = st.text_input("Survey Number (SY. NO.)\nಸರ್ವೆ ಸಂಖ್ಯೆ (SY. NO.)")
village = st.text_input("Village\nಹಳ್ಳಿ")
taluk = st.text_input("Taluk\nತಾಲೂಕು")
epid = st.text_input("EPID (E Khata number)\nಇ-ಖಾತೆ ಸಂಖ್ಯೆ (EPID)")
ward_no = st.text_input("Ward Number\nವಾರ್ಡ್ ಸಂಖ್ಯೆ")
constituency = st.text_input("Constituency Name\nಕ್ಷೇತ್ರದ ಹೆಸರು")
total_builtup = st.number_input("Total Built-up Area (Sq.m)\nಒಟ್ಟು ಕಟ್ಟಡ ವಿಶೇಷ (Sq.m)", min_value=0.0, value=0.0)

# --- Dimensions ---
st.subheader("Plot dimensions (metres) / ಜಾಗದ ಗಾತ್ರ (ಮೀಟರ್)")
site_length_m = st.number_input("Site Length (m)\nಉದ್ದ (ಮೀಟರ್)", min_value=0.1, value=15.0)
site_width_m = st.number_input("Site Width (m)\nಅಗಲ (ಮೀಟರ್)", min_value=0.1, value=12.0)

# --- Roads (bilingual labels) ---
st.subheader("Roads around the site / ಸೈಟ್‌ ಸುತ್ತಲೂ ರಸ್ತೆ")
road_info = {}
for side_en, side_kn in [("North","ಉತ್ತರ"),("South","ದಕ್ಷಿಣ"),("East"," ಪೂರ್ವ"),("West","ಪಶ್ಚಿಮ")]:
    c1, c2 = st.columns([1,1.3])
    with c1:
        exists = st.checkbox(f"{side_en} Road\n{side_kn} ರಸ್ತೆ", value=(side_en=="North"))
    with c2:
        width = st.number_input(f"{side_en} Road Width (m)\n{side_kn} ರಸ್ತೆ ಅಗಲ (ಮೀ)", min_value=0.0, value=6.0 if exists else 0.0, step=0.5, key=f"{side_en}_w")
    road_info[side_en.lower()] = {"exists": exists, "width": width}

# --- Key plan input (address or lat,lon) bilingual ---
st.subheader("Key Plan / ಕೀ ಪ್ಲಾನ್")
kp_center_txt = st.text_input("Key plan center (lat,lon) OR address\nಕೀ ಪ್ಲಾನ್ ಕೇಂದ್ರ (lat,lon) ಅಥವಾ ವಿಳಾಸ")
kp_radius_m = st.number_input("Key plan buffer radius (m)\nಬಫರ್ ವ್ಯಾಸ (ಮೀ)", min_value=50, value=200, step=10)
kp_zoom = st.slider("Key plan zoom (10-19)\nನಕ್ಷೆ ಝೂಮ್", min_value=10, max_value=19, value=16)

# parse geocode
picked_latlon = None
if kp_center_txt.strip():
    if "," in kp_center_txt:
        try:
            a,b = kp_center_txt.split(",",1)
            picked_latlon = (float(a.strip()), float(b.strip()))
            st.success(f"Using coordinates: {picked_latlon[0]:.6f}, {picked_latlon[1]:.6f}")
        except Exception:
            picked_latlon = None
    else:
        # geocode with Nominatim
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search", params={"q":kp_center_txt,"format":"json","limit":1}, headers={"User-Agent":"SingleSitePlan/1.0"}, timeout=6)
            data = r.json()
            if data:
                picked_latlon = (float(data[0]["lat"]), float(data[0]["lon"]))
                st.success(f"Geocoded: {picked_latlon[0]:.6f}, {picked_latlon[1]:.6f}")
        except Exception:
            picked_latlon = None

# If not provided, default to Bangalore center
if not picked_latlon:
    picked_latlon = (12.9715987,77.5945627)

# --- ADLR auto params: ADLR will be a zoomed inset (zoom_adlr = kp_zoom + 3) and 50m buffer
adlr_zoom = min(19, kp_zoom + 3)
adlr_buffer_m = 50

# --- Generate button (creates DXF in metres and PDF) ---
if st.button("Generate DXF + PDF"):
    # Layout constants (in millimetres for page geometry) but DXF units will be metres
    PAGE_W_MM, PAGE_H_MM = 420.0, 297.0
    LEFT, RIGHT, TOP, BOTTOM = 12.0, 12.0, 12.0, 12.0
    INFO_GAP = 15.0
    DRAW_W = PAGE_W_MM * 0.62
    DRAW_H = PAGE_H_MM - TOP - BOTTOM
    DRAW_X = LEFT
    DRAW_Y = BOTTOM
    INFO_X = DRAW_X + DRAW_W + INFO_GAP

    # We'll create DXF units in metres: 1 DXF unit = 1 m
    # For layout coordinates we convert mm -> metres by dividing by 1000 when placing in DXF
    # So page coordinates in DXF: PAGE_W_MM/1000.0 metres width etc.
    page_w_m = PAGE_W_MM / 1000.0
    page_h_m = PAGE_H_MM / 1000.0
    left_m = LEFT / 1000.0

    # Create DXF (units = metres logically)
    doc = ezdxf.new(dxfversion="R2013")
    msp = doc.modelspace()

    # add layers
    for lname in ["BORDER","SITE","ROAD","TEXT","IMAGES"]:
        if lname not in doc.layers:
            doc.layers.add(lname)

    # add dashed linetype
    if "GBA_DASH" not in doc.linetypes:
        # pattern defined in drawing units (positive = dash, negative = gap)
        doc.linetypes.add("GBA_DASH", pattern=[0.16, -0.05, 0.04, -0.05, 0.04, -0.05])

    # ---------- DRAW page border in DXF (metres) ----------
    border_poly = [
        (LEFT/1000.0, BOTTOM/1000.0),
        ((PAGE_W_MM-LEFT)/1000.0, BOTTOM/1000.0),
        ((PAGE_W_MM-LEFT)/1000.0, (PAGE_H_MM-BOTTOM)/1000.0),
        (LEFT/1000.0, (PAGE_H_MM-BOTTOM)/1000.0),
        (LEFT/1000.0, BOTTOM/1000.0)
    ]
    msp.add_lwpolyline(border_poly, dxfattribs={"layer":"BORDER", "closed":True})

    # ---------- Drawing area rectangle (left) ----------
    draw_rect = [
        (DRAW_X/1000.0, DRAW_Y/1000.0),
        ((DRAW_X + DRAW_W)/1000.0, DRAW_Y/1000.0),
        ((DRAW_X + DRAW_W)/1000.0, (DRAW_Y + DRAW_H)/1000.0),
        (DRAW_X/1000.0, (DRAW_Y + DRAW_H)/1000.0),
        (DRAW_X/1000.0, DRAW_Y/1000.0)
    ]
    msp.add_lwpolyline(draw_rect, dxfattribs={"layer":"BORDER", "closed":True})

    # ---------- Fit site into drawing area ----------
    inner_pad_mm = 8.0
    usable_w_mm = DRAW_W - 2*inner_pad_mm
    usable_h_mm = DRAW_H - 2*inner_pad_mm
    # prefer scale 1:100 -> 10 mm per metre -> mm_per_m_default
    mm_per_m_default = 1000.0/100.0
    # compute scale mm per metre to fit
    if (site_width_m * mm_per_m_default <= usable_w_mm) and (site_length_m * mm_per_m_default <= usable_h_mm):
        mm_per_m_use = mm_per_m_default
    else:
        mm_per_m_use = min(usable_w_mm / site_width_m, usable_h_mm / site_length_m)

    # site size in mm on sheet
    site_w_mm_draw = site_width_m * mm_per_m_use
    site_h_mm_draw = site_length_m * mm_per_m_use
    site_x_mm = DRAW_X + inner_pad_mm + (usable_w_mm - site_w_mm_draw)/2.0
    site_y_mm = DRAW_Y + inner_pad_mm + (usable_h_mm - site_h_mm_draw)/2.0

    # Convert site placement to DXF metres (divide by 1000)
    site_x_m = site_x_mm / 1000.0
    site_y_m = site_y_mm / 1000.0
    site_w_m_draw = site_w_mm_draw / 1000.0
    site_h_m_draw = site_h_mm_draw / 1000.0

    # ---------- Site rectangle in DXF (using dashed linetype) ----------
    site_poly = [
        (site_x_m, site_y_m),
        (site_x_m + site_w_m_draw, site_y_m),
        (site_x_m + site_w_m_draw, site_y_m + site_h_m_draw),
        (site_x_m, site_y_m + site_h_m_draw),
        (site_x_m, site_y_m)
    ]
    msp.add_lwpolyline(site_poly, dxfattribs={"layer":"SITE", "linetype":"GBA_DASH", "closed":True})

    # ---------- Roads in DXF (using mm_per_m_use to map metres->mm on sheet then to metres units) ----------
    # We'll draw road polygons around the site using same drawing-scale so they match PDF.
    for side, info in road_info.items():
        if not info["exists"]:
            continue
        w_m = info["width"]
        road_band_mm = w_m * mm_per_m_use
        # compute coordinates in mm, then convert to m for DXF insertion
        if side == "north":
            rx_mm, ry_mm = site_x_mm, site_y_mm + site_h_mm_draw
            poly_mm = [(rx_mm, ry_mm), (rx_mm + site_w_mm_draw, ry_mm), (rx_mm + site_w_mm_draw, ry_mm + road_band_mm), (rx_mm, ry_mm + road_band_mm), (rx_mm, ry_mm)]
            label_mm = (rx_mm + site_w_mm_draw/2.0, ry_mm + road_band_mm/2.0 + 3)
        elif side == "south":
            rx_mm, ry_mm = site_x_mm, site_y_mm - road_band_mm
            poly_mm = [(rx_mm, ry_mm), (rx_mm + site_w_mm_draw, ry_mm), (rx_mm + site_w_mm_draw, ry_mm + road_band_mm), (rx_mm, ry_mm + road_band_mm), (rx_mm, ry_mm)]
            label_mm = (rx_mm + site_w_mm_draw/2.0, ry_mm + road_band_mm/2.0 - 3)
        elif side == "east":
            rx_mm, ry_mm = site_x_mm + site_w_mm_draw, site_y_mm
            poly_mm = [(rx_mm, ry_mm), (rx_mm + road_band_mm, ry_mm), (rx_mm + road_band_mm, ry_mm + site_h_mm_draw), (rx_mm, ry_mm + site_h_mm_draw), (rx_mm, ry_mm)]
            label_mm = (rx_mm + road_band_mm/2.0 + 3, ry_mm + site_h_mm_draw/2.0)
        else:  # west
            rx_mm, ry_mm = site_x_mm - road_band_mm, site_y_mm
            poly_mm = [(rx_mm, ry_mm), (rx_mm + road_band_mm, ry_mm), (rx_mm + road_band_mm, ry_mm + site_h_mm_draw), (rx_mm, ry_mm + site_h_mm_draw), (rx_mm, ry_mm)]
            label_mm = (rx_mm + road_band_mm/2.0 - 3, ry_mm + site_h_mm_draw/2.0)
        poly_m = [(x/1000.0, y/1000.0) for x,y in poly_mm]
        msp.add_lwpolyline(poly_m, dxfattribs={"layer":"ROAD", "closed":True})
        # add label text (height in metres approx)
        tx_m, ty_m = label_mm[0]/1000.0, label_mm[1]/1000.0
        msp.add_text(f"{side.title()} ({w_m:.1f} m ROAD)", dxfattribs={"height":0.006, "layer":"TEXT"}).set_pos((tx_m, ty_m), align="MIDDLE_CENTER")

    # ---------- Site title above site ----------
    msp.add_text(f"SITE (SY.NO. {survey_no})", dxfattribs={"height":0.008, "layer":"TEXT"}).set_pos((site_x_m + site_w_m_draw/2.0, site_y_m + site_h_m_draw + 0.018), align="MIDDLE_CENTER")

    # ---------- RIGHT COLUMN: Key Plan box (drawn in page coords, convert to metres) ----------
    key_w_mm, key_h_mm = 110.0, 70.0
    key_x_mm, key_y_mm = INFO_X, PAGE_H_MM - TOP - key_h_mm
    key_rect_m = [
        (key_x_mm/1000.0, key_y_mm/1000.0),
        ((key_x_mm + key_w_mm)/1000.0, key_y_mm/1000.0),
        ((key_x_mm + key_w_mm)/1000.0, (key_y_mm + key_h_mm)/1000.0),
        (key_x_mm/1000.0, (key_y_mm + key_h_mm)/1000.0),
        (key_x_mm/1000.0, key_y_mm/1000.0)
    ]
    msp.add_lwpolyline(key_rect_m, dxfattribs={"layer":"BORDER", "closed":True})
    # If latlon provided, create keyplan image and insert into DXF
    try:
        kimg = make_keyplan_image(picked_latlon[0], picked_latlon[1], zoom=kp_zoom, radius_m=kp_radius_m, tiles_radius=1, scale=2)
        px_w = int(key_w_mm * 6)
        px_h = int(key_h_mm * 6)
        kimg = kimg.resize((px_w, px_h), Image.LANCZOS)
        tmp_key = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        kimg.convert("RGB").save(tmp_key.name, format="PNG")
        image_def = doc.add_image_def(tmp_key.name, size_in_px=(px_w, px_h))
        msp.add_image(image_def, insert=(key_x_mm/1000.0 + 0.001, key_y_mm/1000.0 + 0.001), size_in_units=(key_w_mm/1000.0 - 0.002, key_h_mm/1000.0 - 0.002))
        # small north arrow drawn as line/text
        na_x_m = (key_x_mm + key_w_mm - 8)/1000.0
        na_y_m = (key_y_mm + key_h_mm - 18)/1000.0
        msp.add_line((na_x_m, na_y_m), (na_x_m, na_y_m + 0.012), dxfattribs={"layer":"BORDER"})
        msp.add_text("N", dxfattribs={"height":0.006, "layer":"TEXT"}).set_pos((na_x_m, na_y_m + 0.014), align="MIDDLE_CENTER")
        tmp_key.close()
    except Exception:
        msp.add_text("KEY PLAN (To be inserted)", dxfattribs={"height":0.005, "layer":"TEXT"}).set_pos(((key_x_mm + key_w_mm/2.0)/1000.0, (key_y_mm + key_h_mm/2.0)/1000.0), align="MIDDLE_CENTER")

    # ---------- ADLR sketch box (below key plan) auto-generated (zoomed) ----------
    adlr_w_mm, adlr_h_mm = 110.0, 65.0
    adlr_x_mm, adlr_y_mm = INFO_X, key_y_mm - adlr_h_mm - 10
    adlr_rect_m = [
        (adlr_x_mm/1000.0, adlr_y_mm/1000.0),
        ((adlr_x_mm + adlr_w_mm)/1000.0, adlr_y_mm/1000.0),
        ((adlr_x_mm + adlr_w_mm)/1000.0, (adlr_y_mm + adlr_h_mm)/1000.0),
        (adlr_x_mm/1000.0, (adlr_y_mm + adlr_h_mm)/1000.0),
        (adlr_x_mm/1000.0, adlr_y_mm/1000.0)
    ]
    msp.add_lwpolyline(adlr_rect_m, dxfattribs={"layer":"BORDER", "closed":True})
    try:
        adlr_img = make_keyplan_image(picked_latlon[0], picked_latlon[1], zoom=adlr_zoom, radius_m=adlr_buffer_m, tiles_radius=1, scale=2)
        px_w = int(adlr_w_mm * 6)
        px_h = int(adlr_h_mm * 6)
        adlr_img = adlr_img.resize((px_w, px_h), Image.LANCZOS)
        tmp_adlr = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        adlr_img.convert("RGB").save(tmp_adlr.name, format="PNG")
        adlr_def = doc.add_image_def(tmp_adlr.name, size_in_px=(px_w, px_h))
        msp.add_image(adlr_def, insert=(adlr_x_mm/1000.0 + 0.001, adlr_y_mm/1000.0 + 0.001), size_in_units=(adlr_w_mm/1000.0 - 0.002, adlr_h_mm/1000.0 - 0.002))
        tmp_adlr.close()
    except Exception:
        msp.add_text("ADLR SKETCH (To be inserted)", dxfattribs={"height":0.005, "layer":"TEXT"}).set_pos(((adlr_x_mm + adlr_w_mm/2.0)/1000.0, (adlr_y_mm + adlr_h_mm/2.0)/1000.0), align="MIDDLE_CENTER")

    # ---------- Land Use Analysis & table below ADLR ----------
    lut_x_mm, lut_y_mm = INFO_X, adlr_y_mm - 10
    tbl_w_mm = 12 + 55 + 30 + 20
    header_y_mm = lut_y_mm + 12
    # header labels (drawn as text)
    xcur_mm = lut_x_mm
    col_w = [12,55,30,20]
    headers = ["SL.No","PARTICULARS","AREA (Sq.m)","%"]
    for i,h in enumerate(headers):
        msp.add_text(h, dxfattribs={"height":0.005, "layer":"TEXT"}).set_pos(((xcur_mm + col_w[i]/2.0)/1000.0, header_y_mm/1000.0), align="MIDDLE_CENTER")
        xcur_mm += col_w[i]
    # sample rows
    rows = [
        ("1","SITE AREA", f"{site_width_m*site_length_m:.1f}", "100.00"),
        ("2","TOTAL SITE AREA", f"{site_width_m*site_length_m:.1f}", "100.00")
    ]
    row_h_mm = 6.5
    for r_idx, row in enumerate(rows):
        y_mm = header_y_mm - (r_idx + 1) * row_h_mm
        xcur_mm = lut_x_mm
        for i,val in enumerate(row):
            msp.add_text(str(val), dxfattribs={"height":0.005, "layer":"TEXT"}).set_pos(((xcur_mm + col_w[i]/2.0)/1000.0, y_mm/1000.0), align="MIDDLE_CENTER")
            xcur_mm += col_w[i]
    # box around table
    msp.add_lwpolyline([(lut_x_mm - 1.5, header_y_mm + 2), (lut_x_mm - 1.5 + tbl_w_mm + 3, header_y_mm + 2),
                        (lut_x_mm - 1.5 + tbl_w_mm + 3, header_y_mm + 2 - (len(rows)+1.2)*row_h_mm),
                        (lut_x_mm - 1.5, header_y_mm + 2 - (len(rows)+1.2)*row_h_mm),
                        (lut_x_mm - 1.5, header_y_mm + 2)], dxfattribs={"layer":"BORDER"})

    # ---------- General Conditions (MTEXT) ----------
    gc_x_mm = INFO_X
    gc_start_y_mm = header_y_mm - (len(rows)+1.2)*row_h_mm - 8
    gc_lines = [
        "1. The single plot layout plan is approved based on the survey sketch certified by the Assistant Director of Land Records.",
        "2. Building construction shall be undertaken only after obtaining approval for the building plan from the city corporation as per the approved single site layout plan.",
        "3. The existing width of road abutting the site in question is marked in the plan. At the time of building plan approval the authority approving the building plan shall allow the maximum FAR permissible considering the minimum width of the road at any stretch towards any one side which shall join a road of equal or higher width.",
        "4. The owner shall provide drinking water, waste water discharge system and drainage system for the site in question. During the building plan approval the owner shall submit a design to implement the rain water harvesting to collect the rain water from the entire site area.",
        "5. Approval of single site layout plan shall not be a document to claim title to the property. In case of pending cases under the Land Reforms Act/Section 136(3) of the Land Revenue Act, 1964, approval of single site layout plan shall be subject to final order. The applicant shall be bound by the final order of the court in this regard and in no case the fees paid for the approval of the single site layout plan will be refunded.",
        "6. If it is found that the land proposed by the applicant includes any land belonging to the Government or any other private land, in such a case, the Authority reserves the rights to modify the single site layout plan or to withdraw the plan.",
        "7. If it is proved that the applicant has provided any false documents or forged documents for the plan sanction, the plan sanction shall stand canceled automatically.",
        "8. The applicant shall be bound to all subsequent orders and the decision relating to payment of fees as required by the Authority.",
        "9. Adequate provisions shall be made to segregate wet waste, dry waste and plastics. Area should be reserved for composting of wet waste, dry waste etc.",
        "10. No Objection Certificates/Approvals for the building plan should be obtained from the competent authorities prior to construction of building on the approved single site.",
        "11. Sewage shall not be discharged into open spaces/vacant areas but should be reused for gardening, cleaning of common areas and various other uses.",
        "12. If the owner wishes to modify the single site layout approval to multi-plot residential layout, the owner shall submit a request to the Greater Bengaluru Authority and obtain approval for the multi-plot residential layout plan as per the zoning regulations.",
        "13. One tree for every 240.0 sq.m of the total floor area shall be planted and nurtured at the site in question.",
        "14. Prior permission should be obtained from the competent authority before constructing a culvert on the storm water drain between the land in question and the existing road attached to it if any.",
        "15. To abide by such other conditions as may be imposed by the Authority from time to time."
    ]
    wrapped_gc = "\n\n".join([textwrap.fill(l, width=80) for l in gc_lines])
    msp.add_mtext(wrapped_gc, dxfattribs={"layer":"TEXT", "height":0.0045, "width":0.11}).set_location((gc_x_mm/1000.0, gc_start_y_mm/1000.0))

    # ---------- Note block ----------
    note_lines = [
        "1. The single plot plan is issued under the provisions of section 17 of KTCP Act 1961.",
        "2. The applicant has remitted fees of Rs.******* vide challan No. ********* Dated : **.**.****.",
        "3. The applicant has to abide by the conditions imposed in the single plot plan approval order.",
        "4. This single plot plan is issued vide number ***/***/***-******* dated : **.**.****."
    ]
    wrapped_note = "\n".join(note_lines)
    note_y_mm = (gc_start_y_mm - 85)
    msp.add_mtext(wrapped_note, dxfattribs={"layer":"TEXT", "height":0.0045, "width":0.11}).set_location((gc_x_mm/1000.0, note_y_mm/1000.0))

    # ---------- Title block with empty signature boxes (no labels) ----------
    tb_x_mm, tb_y_mm, tb_w_mm, tb_h_mm = LEFT, BOTTOM, PAGE_W_MM - LEFT - RIGHT, 35.0
    msp.add_lwpolyline([(tb_x_mm/1000.0, tb_y_mm/1000.0), ((tb_x_mm+tb_w_mm)/1000.0, tb_y_mm/1000.0),
                        ((tb_x_mm+tb_w_mm)/1000.0, (tb_y_mm+tb_h_mm)/1000.0), (tb_x_mm/1000.0, (tb_y_mm+tb_h_mm)/1000.0),
                        (tb_x_mm/1000.0, tb_y_mm/1000.0)], dxfattribs={"layer":"BORDER", "closed":True})
    dv1_m = (tb_x_mm + tb_w_mm*0.48)/1000.0
    dv2_m = (tb_x_mm + tb_w_mm*0.70)/1000.0
    msp.add_line((dv1_m, tb_y_mm/1000.0), (dv1_m, (tb_y_mm+tb_h_mm)/1000.0), dxfattribs={"layer":"BORDER"})
    msp.add_line((dv2_m, tb_y_mm/1000.0), (dv2_m, (tb_y_mm+tb_h_mm)/1000.0), dxfattribs={"layer":"BORDER"})

    # Draw 4 empty signature boxes above title block (right side)
    sig_box_w_mm, sig_box_h_mm = 40.0, 12.0
    sig_start_x_mm = tb_x_mm + tb_w_mm - sig_box_w_mm - 6.0
    sig_start_y_mm = tb_y_mm + tb_h_mm + 6.0
    # create 4 small empty boxes stacked vertically with spacing
    for i in range(4):
        sx = sig_start_x_mm
        sy = sig_start_y_mm + i*(sig_box_h_mm + 4.0)
        msp.add_lwpolyline([(sx/1000.0, sy/1000.0), ((sx+sig_box_w_mm)/1000.0, sy/1000.0),
                            ((sx+sig_box_w_mm)/1000.0, (sy+sig_box_h_mm)/1000.0), (sx/1000.0, (sy+sig_box_h_mm)/1000.0),
                            (sx/1000.0, sy/1000.0)], dxfattribs={"layer":"BORDER", "closed":True})

    # ---------- Save DXF to buffer ----------
    dxf_buf = io.BytesIO()
    doc.write(dxf_buf)
    dxf_buf.seek(0)

    # ---------- Render PDF from the DXF (A3) ----------
    fig = plt.figure(figsize=(PAGE_W_MM/25.4, PAGE_H_MM/25.4), dpi=300)
    ax = fig.add_axes([0,0,1,1])
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(doc.modelspace())
    ax.set_axis_off()
    pdf_buf = io.BytesIO()
    fig.savefig(pdf_buf, format="pdf", bbox_inches="tight", dpi=300)
    plt.close(fig)
    pdf_buf.seek(0)

    # ---------- Streamlit download buttons ----------
    st.success("DXF and PDF generated (DXF units = metres; PDF English-only).")
    st.download_button("Download DXF", data=dxf_buf.getvalue(), file_name=f"Single_Site_{survey_no or 'site'}.dxf", mime="application/dxf")
    st.download_button("Download PDF", data=pdf_buf.getvalue(), file_name=f"Single_Site_{survey_no or 'site'}.pdf", mime="application/pdf")

    # cleanup temp images created
    # Note: leaving them is OK; optional cleanup could remove earlier tmp files if desired
