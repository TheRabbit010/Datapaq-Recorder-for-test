import io
import os
import re
import struct
import zlib
import numpy as np
import olefile
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from PIL import Image
from datetime import datetime, timedelta

# ==============================================================================
# STREAMLIT PAGE CONFIGURATION & CSS STYLING
# ==============================================================================
st.set_page_config(page_title="Furnace Profiler & Timeline Sync", page_icon="🔥", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 700 !important; white-space: normal !important; line-height: 1.2 !important; }
div[data-testid="stMetricLabel"] { font-size: 1.1rem !important; font-weight: 500 !important; color: #a0aab2 !important; }
button[data-baseweb="tab"] { font-size: 1.2rem !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONSTANTS & CONFIGURATIONS
# ==============================================================================
PROBE_COLORS = {"PB#1": "#ff0000", "PB#2": "#00ff00", "PB#3": "#0000ff", "PB#4": "#8b4513", "PB#5": "#ff00ff", "PB#6": "#b8860b", "PB#7": "#800080", "PB#8": "#00ffff", "PB#9": "#d32f2f", "PB#10": "#5c4033"}

FURNACE_CONFIGS = {
    "NB1": {"line_speed_mpm": 1.400, "trigger_temp_brazing": 577.0},
    "NB2": {"line_speed_mpm": 1.560, "trigger_temp_brazing": 577.0},
    "NB3": {"line_speed_mpm": 1.270, "trigger_temp_brazing": 577.0}
}

CH_NB1 = [
    ('CH001', 'Top Z#1', '°C'), ('CH002', 'Top Z#2', '°C'), ('CH003', 'Top Z#3', '°C'), ('CH004', 'Top Z#4', '°C'), ('CH005', 'Top Z#5', '°C'), ('CH006', 'Top Z#6', '°C'), ('CH007', 'Top Z#7', '°C'),
    ('CH008', 'Bottom Z#1', '°C'), ('CH009', 'Bottom Z#2', '°C'), ('CH010', 'Bottom Z#3', '°C'), ('CH011', 'Bottom Z#4', '°C'), ('CH012', 'Bottom Z#5', '°C'), ('CH013', 'Bottom Z#6', '°C'), ('CH014', 'Bottom Z#7', '°C'),
    ('CH015', 'EXIT O2', 'ppm'), ('CH019', 'ENTRANCE O2', 'ppm'),
    ('CH016', 'Dryer #1', '°C'), ('CH017', 'Dryer #2', '°C'),
    ('CH018', 'N2 .1', 'm3/hr'), ('CH020', 'DEW POINT', 'Cdp')
]

CH_NB2 = [
    ('CH001', 'Top Z#1', '°C'), ('CH002', 'Top Z#2', '°C'), ('CH003', 'Top Z#3', '°C'), ('CH004', 'Top Z#4', '°C'), ('CH005', 'Top Z#5', '°C'), ('CH006', 'Top Z#6', '°C'), ('CH007', 'Top Z#7', '°C'),
    ('CH008', 'Bottom Z#1', '°C'), ('CH009', 'Bottom Z#2', '°C'), ('CH010', 'Bottom Z#3', '°C'), ('CH011', 'Bottom Z#4', '°C'), ('CH012', 'Bottom Z#5', '°C'), ('CH013', 'Bottom Z#6', '°C'), ('CH014', 'Bottom Z#7', '°C'),
    ('CH015', 'O2 EXIT', 'ppm'), ('CH018', 'O2 ENTRANCE', 'ppm'),
    ('CH016', 'Dryer #1', '°C'), ('CH017', 'Dryer #2', '°C')
]

# ==============================================================================
# PAQ PARSING FUNCTIONS
# ==============================================================================
def decompress_stream(ole_obj, stream_name):
    try:
        raw_data = ole_obj.openstream(stream_name).read()
        zlib_data = raw_data[8:] if raw_data.startswith(b'ZLIB') else raw_data
        try: return zlib.decompress(zlib_data)
        except: return zlib.decompress(zlib_data, -zlib.MAX_WBITS)
    except: return None

def extract_probe_series_autonomously(decomp_bytes):
    best_series = []
    for offset in range(0, min(12000, len(decomp_bytes) - 800), 1):
        rem = len(decomp_bytes) - offset
        cnt = rem // 8
        if cnt < 500: continue
        try: vals = struct.unpack(f"<{cnt}d", decomp_bytes[offset : offset + cnt * 8])
        except: continue
        clean_vals, glitch_count = [], 0
        for v in vals:
            if isinstance(v, float) and -50.0 <= v <= 1000.0:
                clean_vals.append(v)
                glitch_count = 0
            else:
                glitch_count += 1
                if len(clean_vals) > 500:
                    if glitch_count <= 30: clean_vals.append(clean_vals[-1] if clean_vals else 0.0)
                    else: break
                elif glitch_count > 3: clean_vals = []
        if len(clean_vals) > len(best_series) and max(clean_vals) > 100.0:
            best_series = clean_vals
    return best_series

def clean_paq_text(raw_text):
    if not raw_text: return ""
    text = re.split(r'\\\\', raw_text)[0]
    parts = re.split(r'\b(?:CProbe|CSampleInterval|CAxisCustomUnits|CPaqfile|CByteDataArray|CProbeResult|CFurnaceRecipe|CZoom)\b', text)
    cleaned_parts = []
    for p in parts:
        p = re.sub(r'^[>#;\.,\|]+', '', p).strip() 
        if len(p) >= 3 and not re.search(r'([^\-\/0-9])\1{4,}', p):
            cleaned_parts.append(p)
    return " ".join(cleaned_parts)

@st.cache_data
def process_paq_file(file_bytes, filename):
    ole_bytes = io.BytesIO(file_bytes)
    ole = olefile.OleFileIO(ole_bytes)
    raw_texts = []
    
    for stream_path in ole.listdir():
        try:
            raw_b = ole.openstream(stream_path).read()
            if not raw_b: continue
            data_b = raw_b
            if raw_b.startswith(b'ZLIB') or b'x\x9c' in raw_b[:20]:
                try: data_b = zlib.decompress(raw_b[8:] if raw_b.startswith(b'ZLIB') else raw_b)
                except:
                    try: data_b = zlib.decompress(raw_b[8:] if raw_b.startswith(b'ZLIB') else raw_b, -zlib.MAX_WBITS)
                    except: pass
            ascii_matches = re.findall(rb'[\x20-\x7E]{4,}', data_b)
            for m in ascii_matches: raw_texts.append(m.decode('ascii', errors='ignore').strip())
        except: continue

    probe_streams = [s for s in ole.listdir() if len(s) >= 4 and s[0] == 'Paqfiles' and s[2] == 'ProbeResults']
    probe_streams = sorted(probe_streams, key=lambda x: x[-1])

    all_probes = {}
    for idx, stream_path in enumerate(probe_streams):
        col_name = f"PB#{idx+1}"
        d = decompress_stream(ole, "/".join(stream_path))
        if d:
            series = extract_probe_series_autonomously(d)
            if series: all_probes[col_name] = series

    max_samples = max(len(v) for v in all_probes.values()) if all_probes else 0
    if max_samples == 0: return None

    aligned_probes = {k: (v + [np.nan] * (max_samples - len(v)) if len(v) < max_samples else v) for k, v in all_probes.items()}
    df_master = pd.DataFrame(aligned_probes)
    df_master.insert(0, "Time_Seconds", range(len(df_master)))
    
    probe_cols = [f"PB#{i}" for i in range(1, 11) if f"PB#{i}" in df_master.columns]
    
    recipe_corpus = f"{filename} " + " ".join([clean_paq_text(s) for s in raw_texts])
    furnace_id, furnace_variant = "NB3", "NB3"
    
    if re.search(r'\b(KE8|M2|EVO)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB3", "NB3 (KE8 : M2/EVO)"
    elif re.search(r'\bRAD\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB1", "NB1 (RAD)"
    elif re.search(r'\b(CDS|KN9|12SHP)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB1", "NB1 (CDS/KN9/12SHP)"
    elif re.search(r'\bBTM\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB3", "NB3 (BTM)"
    elif re.search(r'\b(Utahc|UT)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB2", "NB2 (Utahc)"
    elif re.search(r'\b(Tahc|G2|NB2)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB2", "NB2 (Tahc)"
    elif re.search(r'\bNB3\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB3", "NB3"
    elif re.search(r'\bWK\d{1,2}\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB1", "NB1 (Standard)"
    else:
        f_match = re.search(r'NB\s*Furnace\s*0?([123])\b|NB-0?([123])\b', recipe_corpus, re.IGNORECASE)
        if f_match: 
            found_num = next(g for g in f_match.groups() if g is not None)
            furnace_id = furnace_variant = f"NB{found_num}"

    base_cfg = FURNACE_CONFIGS.get(furnace_id, FURNACE_CONFIGS["NB3"])
    line_speed_mpm = base_cfg["line_speed_mpm"]

    return {
        "filename": filename, "df_master": df_master, "probe_cols": probe_cols, "invalid_cols": [], 
        "furnace_id": furnace_id, "furnace_variant": furnace_variant, "cfg": base_cfg, "line_speed_mpm": line_speed_mpm
    }

# ==============================================================================
# RECORDER PARSING FUNCTIONS
# ==============================================================================
def find_dad_params(raw):
    if len(raw) < 5000: return None, None 
    max_search = min(80000, len(raw) - 1000)
    for offset in range(1000, max_search):
        yr, mo, dy, hr, mn, sc = raw[offset:offset+6]
        if 0 <= yr <= 99 and 1 <= mo <= 12 and 1 <= dy <= 31 and 0 <= hr <= 23 and 0 <= mn <= 59 and 0 <= sc <= 59:
            for rs in range(24, 1024, 2): 
                valid_chain = True
                for step in range(1, 4):
                    check_pos = offset + (rs * step)
                    if check_pos + 6 >= len(raw):
                        valid_chain = False; break
                    y2, m2, d2, h2, min2, s2 = raw[check_pos:check_pos+6]
                    if not (0 <= y2 <= 99 and 1 <= m2 <= 12 and 1 <= d2 <= 31 and 0 <= h2 <= 23 and 0 <= min2 <= 59 and 0 <= s2 <= 59):
                        valid_chain = False; break
                if valid_chain: return offset, rs
    return None, None 

def parse_dad(raw: bytes, active_channels):
    records = []
    offset, record_size = find_dad_params(raw)
    if offset is None or record_size is None: return records 
    bpc = 4 if record_size >= 70 else 2
    total = (len(raw) - offset) // record_size
    for i in range(total):
        base = offset + i * record_size
        hdr  = raw[base:base+8]
        if len(hdr) < 8: break
        yr, mo, dy, hr, mn, sc = hdr[0], hdr[1], hdr[2], hdr[3], hdr[4], hdr[5]
        if not (0 <= yr <= 99 and 1 <= mo <= 12 and 1 <= dy <= 31 and 0 <= hr <= 23 and 0 <= mn <= 59 and 0 <= sc <= 59): continue
        parsed_yr = (2000 + yr) if yr < 80 else (1900 + yr)
        try: ts = datetime(parsed_yr, mo, dy, hr, mn, sc)
        except ValueError: continue
        rec = {'DateTime': ts}
        for ch, name, unit in active_channels:
            ch_idx = int(ch.replace('CH', '')) - 1
            data_pos = base + 8 + (ch_idx * bpc)
            if data_pos + 2 > base + record_size: continue
            v1 = struct.unpack_from('>h', raw, data_pos)[0]
            if bpc == 4 and data_pos + 4 <= base + record_size:
                v2 = struct.unpack_from('>h', raw, data_pos + 2)[0]
                min_v, max_v = min(v1, v2), max(v1, v2)
            else:
                min_v = max_v = v1
            
            divisor = 1.0 if name == 'N2 .1' else 10.0
            if v1 not in (-32768, -32767, 32767, 32766) and (-32000 < v1 < 32000):
                rec[name] = max_v / divisor
        records.append(rec)
    return records

@st.cache_data
def process_dad_files(files_data, active_channels):
    all_records = []
    for fname, raw in files_data:
        recs = parse_dad(raw, active_channels)
        if len(recs) > 10: all_records.extend(recs[3:-2])
        else: all_records.extend(recs)
    if not all_records: return pd.DataFrame()
    df = pd.DataFrame(all_records).drop_duplicates('DateTime').sort_values('DateTime').reset_index(drop=True)
    return df

@st.cache_data
def parse_nb3_csv(files_data):
    combined_dfs = []
    for fname, raw_bytes in files_data:
        text_content = raw_bytes.decode('utf-8', errors='ignore')
        lines = text_content.splitlines()
        endheader_cols = []
        for line in lines[:150]:
            if line.strip().startswith("#EndHeader"):
                endheader_cols = [x.strip() for x in line.strip().split(",")]
                break
        
        has_z6_z7 = bool(re.search(r'TH_CH6', text_content, re.I))
        if not has_z6_z7: continue
        
        data_rows = []
        date_regex = re.compile(r'^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}')
        time_regex = re.compile(r'^\d{1,2}:\d{2}:\d{2}')
        curr_date = ""

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#EndHeader"): continue
            if date_regex.match(line_str) and "," not in line_str:
                curr_date = line_str; continue
            parts = [p.strip() for p in line_str.split(",")]
            if date_regex.search(parts[0]): data_rows.append(parts)
            elif time_regex.search(parts[0]):
                dt_str = f"{curr_date} {parts[0]}".strip() if curr_date else parts[0]
                data_rows.append([dt_str] + parts[1:])
                
        if not data_rows: continue
        data_df = pd.DataFrame(data_rows)
        df = pd.DataFrame()
        df["DateTime"] = pd.to_datetime(data_df[0], errors="coerce", dayfirst=True)
        
        def extract(c_idx, fb_idx):
            idx = c_idx if c_idx is not None else fb_idx
            if idx is not None and idx < data_df.shape[1]:
                return pd.to_numeric(data_df[idx], errors="coerce")
            return pd.Series([None] * len(data_df))

        for i in range(1, 8):
            c = next((idx for idx, name in enumerate(endheader_cols) if re.search(rf'1\)TH_CH{i}Max', name, re.I)), None)
            df[f"Top Z#{i}"] = extract(c, 2 + (i - 1) * 3)
            
        for i in range(1, 8):
            c = next((idx for idx, name in enumerate(endheader_cols) if re.search(rf'2\)TH_CH{i}Max', name, re.I)), None)
            df[f"Bottom Z#{i}"] = extract(c, 2 + (7 + i - 1) * 3)
            
        dryoff_names = ["DRYOFF1", "DRYOFF2", "DRYOFF3"]
        for i in range(1, 4):
            c = next((idx for idx, name in enumerate(endheader_cols) if re.search(rf'3\)TH_CH{i}Max', name, re.I)), None)
            df[dryoff_names[i-1]] = extract(c, 2 + (14 + i - 1) * 3)

        c_o2_exit = next((idx for idx, name in enumerate(endheader_cols) if re.search(r'3\)TH_CH4Max', name, re.I)), None)
        df["Oxygen EXIT"] = extract(c_o2_exit, 2 + (17) * 3)
        c_o2_ent = next((idx for idx, name in enumerate(endheader_cols) if re.search(r'3\)TH_CH5Max', name, re.I)), None)
        df["Oxygen ENTRANCE"] = extract(c_o2_ent, 2 + (18) * 3)
        
        c_n2_exit = next((idx for idx, name in enumerate(endheader_cols) if re.search(r'3\)TH_CH7Max', name, re.I)), None)
        df["N2 Exit"] = extract(c_n2_exit, 2 + (20) * 3)
        c_n2_ent = next((idx for idx, name in enumerate(endheader_cols) if re.search(r'3\)TH_CH8Max', name, re.I)), None)
        df["N2 Entrance"] = extract(c_n2_ent, 2 + (21) * 3)

        c_cool = next((idx for idx, name in enumerate(endheader_cols) if re.search(r'3\)TH_CH6Max', name, re.I)), None)
        df["COOL WATER TEMP"] = extract(c_cool, 2 + (19) * 3)
            
        combined_dfs.append(df.dropna(subset=["DateTime"]))
        
    if not combined_dfs: return pd.DataFrame()
    return pd.concat(combined_dfs, ignore_index=True).drop_duplicates("DateTime").sort_values("DateTime").reset_index(drop=True)

@st.cache_data
def parse_nb1_debinder_csv(files_data):
    combined_dfs = []
    for fname, raw_bytes in files_data:
        text_content = raw_bytes.decode('utf-8', errors='ignore')
        lines = text_content.splitlines()
        parsed_rows = []
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("20") and "," in line_str:
                parts = [p.strip() for p in line_str.split(",")]
                if len(parts) >= 17:
                    try: parsed_rows.append({"DateTime": parts[0], "Zone #1": float(parts[4]), "Zone #2": float(parts[7]), "Zone #3": float(parts[10]), "Zone #4": float(parts[13]), "Combustion Air Temp": float(parts[16])})
                    except: pass
        if parsed_rows:
            df = pd.DataFrame(parsed_rows)
            df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
            combined_dfs.append(df.dropna(subset=["DateTime"]))
    if not combined_dfs: return pd.DataFrame()
    return pd.concat(combined_dfs, ignore_index=True).drop_duplicates("DateTime").sort_values("DateTime").reset_index(drop=True)

# ==============================================================================
# HELPER FOR DRAWING SUB-CHARTS (PROFESSIONAL STYLING)
# ==============================================================================
def draw_line_chart(df_rec, y_cols, title, y_title, x_range, secondary_y_cols=None, secondary_y_title=None, height=520, paq_df=None, paq_cols=None, paq_colors=None, y_range=None):
    fig = make_subplots(specs=[[{"secondary_y": bool(secondary_y_cols)}]])
    
    # 🎨 ปรับชุดสีสำหรับ Recorder ให้มองเห็นชัดเจน เป็นมืออาชีพ
    rec_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]
    
    # 1. กราฟ Recorder (Background) -> ปรับเป็นเส้นประยาว (dash) หนา 2 และความเข้ม 0.9
    for i, col in enumerate(y_cols):
        if col in df_rec.columns:
            fig.add_trace(go.Scatter(
                x=df_rec["DateTime"], y=df_rec[col], 
                name=f"REC: {col}", mode="lines", 
                line=dict(width=2, dash="dash", color=rec_colors[i % len(rec_colors)]), 
                opacity=0.9
            ), secondary_y=False)
            
    # 2. กราฟ Recorder แกนรอง (เช่น N2) -> ใช้เส้นประจุด (dot) ให้ต่างกัน
    if secondary_y_cols:
        sec_colors = ["#17becf", "#bcbd22", "#ff9896"]
        for i, col in enumerate(secondary_y_cols):
            if col in df_rec.columns:
                fig.add_trace(go.Scatter(
                    x=df_rec["DateTime"], y=df_rec[col], 
                    name=f"REC: {col}", mode="lines", 
                    line=dict(width=2, dash="dot", color=sec_colors[i % len(sec_colors)]),
                    opacity=0.9
                ), secondary_y=True)
                
    # 3. กราฟ PAQ (Foreground) -> เส้นทึบหนา 2.5 ชัดเจน
    if paq_df is not None and paq_cols is not None:
        for col in paq_cols:
            c = paq_colors.get(col) if paq_colors else None
            fig.add_trace(go.Scatter(
                x=paq_df["Real_DateTime"], y=paq_df[col], 
                name=f"PAQ: {col}", mode="lines", 
                line=dict(color=c, width=2.5)
            ), secondary_y=False)

    # 4. ตั้งค่าแกน Y และ Layout หลัก
    layout_yaxis = dict(title=y_title, showgrid=True, zeroline=False)
    if y_range:
        layout_yaxis["range"] = y_range

    fig.update_layout(
        title=dict(text=title, font=dict(size=18, weight="bold")), 
        hovermode="x unified", 
        height=height,
        xaxis=dict(title="Real Date & Time", type="date", range=x_range, showgrid=True),
        yaxis=layout_yaxis,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=dict(size=12)),
        margin=dict(l=60, r=120, t=60, b=40)
    )
    
    if secondary_y_cols:
        fig.update_layout(yaxis2=dict(title=secondary_y_title, overlaying="y", side="right", showgrid=False))
        
    st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# STREAMLIT UI LAYOUT & MAIN APPLICATION
# ==============================================================================
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

with st.sidebar:
    st.header("📁 1. Upload PAQ File")
    if st.button("🔄 Reset / Clear Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.uploader_key += 1
        st.rerun()
        
    uploaded_paq = st.file_uploader("Upload Main .PAQ File", type=["paq"], key=f"paq_{st.session_state.uploader_key}")

if not uploaded_paq:
    st.info("👈 Please upload a `.paq` binary file to detect the furnace and reveal recorder upload options.")
    st.stop()

data_paq = process_paq_file(uploaded_paq.getvalue(), uploaded_paq.name)
if not data_paq:
    st.error("❌ Failed to parse valid probe temperature streams from the uploaded PAQ file.")
    st.stop()

furnace_id = data_paq["furnace_id"]
f_variant = data_paq["furnace_variant"]
df_paq = data_paq["df_master"]
probe_cols = data_paq["probe_cols"]

st.success(f"✅ PAQ File Loaded: **{uploaded_paq.name}** | Detected Furnace: **{f_variant}**")

st.sidebar.header(f"📁 2. Upload Recorder Data for {furnace_id}")

recorder_files = None
debinder_files = None

if furnace_id == "NB3":
    recorder_files = st.sidebar.file_uploader("Upload NB3 Recorder (.csv)", type=["csv"], accept_multiple_files=True, key=f"nb3_{st.session_state.uploader_key}")
elif furnace_id == "NB2":
    recorder_files = st.sidebar.file_uploader("Upload NB2 Recorder (.DAD)", type=["dad", "DAD"], accept_multiple_files=True, key=f"nb2_{st.session_state.uploader_key}")
elif furnace_id == "NB1":
    recorder_files = st.sidebar.file_uploader("Upload NB1 Recorder (.DAD)", type=["dad", "DAD"], accept_multiple_files=True, key=f"nb1_{st.session_state.uploader_key}")
    debinder_files = st.sidebar.file_uploader("Upload NB1 Debinder (.csv)", type=["csv"], accept_multiple_files=True, key=f"db_{st.session_state.uploader_key}")

st.sidebar.markdown("---")
st.sidebar.header("⏱️ Align PAQ Time")
st.sidebar.markdown("ระบุวัน/เวลาที่ PAQ เข้าเตาให้ตรงกับ Recorder")
paq_real_start = st.sidebar.date_input("PAQ Run Date", value=datetime.today())
paq_real_time = st.sidebar.time_input("PAQ Start Time (เข้าเตา)", value=datetime.strptime("12:00:00", "%H:%M:%S").time())

real_start_datetime = datetime.combine(paq_real_start, paq_real_time)
df_paq["Real_DateTime"] = real_start_datetime + pd.to_timedelta(df_paq["Time_Seconds"], unit="s")
paq_start = df_paq["Real_DateTime"].min()
paq_end = df_paq["Real_DateTime"].max()

tabs = st.tabs(["⏱️ Timeline Sync (PAQ + All Recorders)", "📊 PAQ Original Profile"])

with tabs[0]:
    if not recorder_files and not debinder_files:
        st.info(f"👉 กรุณาอัปโหลดไฟล์ Recorder ของ {furnace_id} ที่เมนูด้านซ้าย เพื่อดูกราฟซ้อนทับ (Timeline Sync)")
    else:
        df_recorder = pd.DataFrame()
        df_debinder = pd.DataFrame()
        
        if furnace_id == "NB3" and recorder_files:
            df_recorder = parse_nb3_csv([(f.name, f.read()) for f in recorder_files])
        elif furnace_id == "NB2" and recorder_files:
            df_recorder = process_dad_files([(f.name, f.read()) for f in recorder_files], CH_NB2)
        elif furnace_id == "NB1":
            if recorder_files:
                df_recorder = process_dad_files([(f.name, f.read()) for f in recorder_files], CH_NB1)
            if debinder_files:
                df_debinder = parse_nb1_debinder_csv([(f.name, f.read()) for f in debinder_files])

        valid_rec = not df_recorder.empty and (paq_start >= df_recorder["DateTime"].min() and paq_end <= df_recorder["DateTime"].max())
        valid_deb = not df_debinder.empty and (paq_start >= df_debinder["DateTime"].min() and paq_end <= df_debinder["DateTime"].max())

        if (not df_recorder.empty and not valid_rec) or (not df_debinder.empty and not valid_deb):
            st.error("⚠️ คำเตือน: วัน/เวลาของไฟล์ PAQ ไม่อยู่ในช่วงข้อมูล Recorder หรือ Debinder ที่อัปโหลด")
            st.info("👉 กรุณาอัปโหลดไฟล์ Recorder ชุดใหม่ให้ตรง หรือปรับตั้งเวลาเริ่ม PAQ ใหม่ที่เมนูซ้ายมือ")
        
        elif not df_recorder.empty or not df_debinder.empty:
            st.success(f"✅ วันและเวลาของ PAQ ({paq_start.strftime('%H:%M')}) อยู่ในช่วงข้อมูลของ Recorder (นำกราฟซ้อนกันได้)")
            x_range_view = [paq_start - timedelta(minutes=3), paq_end + timedelta(minutes=3)]
            
            # บังคับสเกลแกน Y ที่ 0-650 ตลอด
            forced_y_range = [0, 650]
            
            # =======================================================
            # 1. Recorder: Top Zones
            # =======================================================
            if not df_recorder.empty:
                rec_top_cols = [c for c in df_recorder.columns if "Top Z#" in c]
                if rec_top_cols:
                    draw_line_chart(df_recorder, rec_top_cols, "1. Recorder: Top Zones", "Temperature (°C)", x_range_view, paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)
            
            # =======================================================
            # 2. Recorder: Bottom Zones
            # =======================================================
            if not df_recorder.empty:
                bot_cols = [c for c in df_recorder.columns if "Bottom Z#" in c]
                if bot_cols:
                    draw_line_chart(df_recorder, bot_cols, "2. Recorder: Bottom Zones", "Temperature (°C)", x_range_view, paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)
            
            # =======================================================
            # 3. Recorder: Dryer Zones
            # =======================================================
            if not df_recorder.empty:
                dry_cols = [c for c in df_recorder.columns if "Dryer" in c or "DRYOFF" in c]
                if dry_cols:
                    draw_line_chart(df_recorder, dry_cols, "3. Recorder: Dryer Zones", "Temperature (°C)", x_range_view, paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)
                    
            # =======================================================
            # 4. Recorder: Debinder Zones (เฉพาะ NB1)
            # =======================================================
            if furnace_id == "NB1" and not df_debinder.empty:
                db_cols = [c for c in df_debinder.columns if "Zone #" in c]
                draw_line_chart(df_debinder, db_cols, "4. Recorder: Debinder Zones (NB1)", "Temperature (°C)", x_range_view, ["Combustion Air Temp"], "Comb Air Temp (°C)", paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)
                
            # =======================================================
            # 5. Recorder: Oxygen (ppm) & N2 Flow Rate
            # =======================================================
            if not df_recorder.empty:
                o2_cols = [c for c in df_recorder.columns if "O2" in c or "Oxygen" in c]
                n2_cols = [c for c in df_recorder.columns if "N2" in c]
                if o2_cols or n2_cols:
                    # คง Y หลักที่ 0-650 เพื่อรองรับการโชว์ PAQ Temp ซ้อน
                    draw_line_chart(df_recorder, o2_cols, "5. Recorder: Oxygen (ppm) & N2 Flow Rate", "Oxygen (ppm) / PAQ Temp (°C)", x_range_view, n2_cols, "N2 Flow Rate", paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)
            
            # =======================================================
            # 6. Recorder: Dew Point (NB1) / Cool Water (NB3)
            # =======================================================
            if not df_recorder.empty:
                dew_cols = [c for c in df_recorder.columns if "DEW POINT" in c]
                cool_cols = [c for c in df_recorder.columns if "COOL WATER" in c]
                
                # ถ้ามี Dew Point, อาจจะติดลบได้ เลยให้ Y range ต่ำกว่า 0 
                if dew_cols:
                    draw_line_chart(df_recorder, dew_cols, "6. Recorder: Dew Point", "Dew Point (Cdp) / PAQ Temp (°C)", x_range_view, paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=[-100, 650])
                if cool_cols:
                    draw_line_chart(df_recorder, cool_cols, "6. Recorder: Cool Water Temp", "Temperature (°C)", x_range_view, paq_df=df_paq, paq_cols=probe_cols, paq_colors=PROBE_COLORS, y_range=forced_y_range)

with tabs[1]:
    st.subheader(f"Global Furnace Profile (Standalone) - {f_variant}")
    fig_orig = go.Figure()
    for col in probe_cols:
        fig_orig.add_trace(go.Scatter(x=df_paq["Time_Seconds"], y=df_paq[col], name=col, line=dict(color=PROBE_COLORS.get(col))))
    
    # บังคับสเกล 0-650°C สำหรับกราฟ PAQ เดี่ยวด้วย
    fig_orig.update_layout(title=f"Original PAQ Profile: {data_paq['filename']}", xaxis_title="Time (Seconds)", yaxis_title="Temperature (°C)", yaxis=dict(range=[0, 650]), height=500, hovermode="x unified")
    st.plotly_chart(fig_orig, use_container_width=True)
