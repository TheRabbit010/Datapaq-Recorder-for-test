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

# YOKOGAWA DAD CHANNELS (Recorder)
CH_NB1 = [('CH001', 'Top Z#1', '°C'), ('CH002', 'Top Z#2', '°C'), ('CH003', 'Top Z#3', '°C'), ('CH004', 'Top Z#4', '°C'), ('CH005', 'Top Z#5', '°C'), ('CH006', 'Top Z#6', '°C'), ('CH007', 'Top Z#7', '°C')]
CH_NB2 = [('CH001', 'Top Z#1', '°C'), ('CH002', 'Top Z#2', '°C'), ('CH003', 'Top Z#3', '°C'), ('CH004', 'Top Z#4', '°C'), ('CH005', 'Top Z#5', '°C'), ('CH006', 'Top Z#6', '°C'), ('CH007', 'Top Z#7', '°C')]

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
    
    # ==========================================
    # Furnace Detection Logic (แก้ไขให้รวม filename เพื่ออ่านค่า EVO)
    # ==========================================
    recipe_corpus = f"{filename} " + " ".join([clean_paq_text(s) for s in raw_texts])
    
    furnace_id, furnace_variant = "NB3", "NB3"
    
    # ลำดับความสำคัญในการค้นหา (Specific ก่อน)
    if re.search(r'\b(KE8|M2|EVO)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3 (KE8 : M2/EVO)"
    elif re.search(r'\bRAD\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (RAD)"
    elif re.search(r'\b(CDS|KN9|12SHP)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (CDS/KN9/12SHP)"
    elif re.search(r'\bBTM\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3 (BTM)"
    elif re.search(r'\b(Utahc|UT)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB2", "NB2 (Utahc)"
    elif re.search(r'\b(Tahc|G2|NB2)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB2", "NB2 (Tahc)"
    elif re.search(r'\bNB3\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3"
    elif re.search(r'\bWK\d{1,2}\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (Standard)"
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
            if v1 not in (-32768, -32767, 32767, 32766) and (-32000 < v1 < 32000):
                rec[name] = max_v / 10.0
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
                    try: parsed_rows.append({"DateTime": parts[0], "Zone #1": float(parts[4]), "Zone #2": float(parts[7]), "Zone #3": float(parts[10]), "Zone #4": float(parts[13])})
                    except: pass
        if parsed_rows:
            df = pd.DataFrame(parsed_rows)
            df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
            combined_dfs.append(df.dropna(subset=["DateTime"]))
    if not combined_dfs: return pd.DataFrame()
    return pd.concat(combined_dfs, ignore_index=True).drop_duplicates("DateTime").sort_values("DateTime").reset_index(drop=True)

# ==============================================================================
# STREAMLIT UI LAYOUT & MAIN APPLICATION (INTEGRATED TIMELINE)
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

# 1. ประมวลผลไฟล์ PAQ เพื่อหาประเภทเตา
data_paq = process_paq_file(uploaded_paq.getvalue(), uploaded_paq.name)
if not data_paq:
    st.error("❌ Failed to parse valid probe temperature streams from the uploaded PAQ file.")
    st.stop()

furnace_id = data_paq["furnace_id"]
f_variant = data_paq["furnace_variant"]
df_paq = data_paq["df_master"]
probe_cols = data_paq["probe_cols"]

st.success(f"✅ PAQ File Loaded: **{uploaded_paq.name}** | Detected Furnace: **{f_variant}**")

# 2. Dynamic Uploaders ตามประเภทของเตาที่ตรวจพบจาก PAQ
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

# 3. ให้ผู้ใช้ระบุเวลาจริงที่นำ Datapaq เข้าเตา เพื่อนำกราฟไปทาบให้ตรงเวลาจริงของ Recorder
st.sidebar.markdown("---")
st.sidebar.header("⏱️ Align PAQ Time")
st.sidebar.markdown("ระบุวัน/เวลาที่ PAQ เข้าเตาให้ตรงกับ Recorder")
paq_real_start = st.sidebar.date_input("PAQ Run Date", value=datetime.today())
paq_real_time = st.sidebar.time_input("PAQ Start Time (เข้าเตา)", value=datetime.strptime("12:00:00", "%H:%M:%S").time())

# คำนวณ DateTime ของ PAQ
real_start_datetime = datetime.combine(paq_real_start, paq_real_time)
df_paq["Real_DateTime"] = real_start_datetime + pd.to_timedelta(df_paq["Time_Seconds"], unit="s")
paq_start = df_paq["Real_DateTime"].min()
paq_end = df_paq["Real_DateTime"].max()

# ==============================================================================
# MAIN TABS (TIMELINE SYNC)
# ==============================================================================
tabs = st.tabs(["⏱️ Timeline Sync (PAQ + Recorder)", "📊 PAQ Original Profile"])

with tabs[0]:
    if not recorder_files and not debinder_files:
        st.info(f"👉 กรุณาอัปโหลดไฟล์ Recorder ของ {furnace_id} ที่เมนูด้านซ้าย เพื่อดูกราฟซ้อนทับ (Timeline Sync)")
    else:
        df_recorder = pd.DataFrame()
        rec_y_cols = []
        
        # Parse Recorder data based on Furnace ID
        if furnace_id == "NB3" and recorder_files:
            files_data = [(f.name, f.read()) for f in recorder_files]
            df_recorder = parse_nb3_csv(files_data)
            rec_y_cols = [c for c in df_recorder.columns if "Top Z#" in c]
            
        elif furnace_id == "NB2" and recorder_files:
            files_data = [(f.name, f.read()) for f in recorder_files]
            df_recorder = process_dad_files(files_data, CH_NB2)
            rec_y_cols = [c for c in df_recorder.columns if "Top Z#" in c]
            
        elif furnace_id == "NB1":
            if recorder_files:
                files_data = [(f.name, f.read()) for f in recorder_files]
                df_recorder = process_dad_files(files_data, CH_NB1)
                rec_y_cols = [c for c in df_recorder.columns if "Top Z#" in c]
            elif debinder_files:
                files_data = [(f.name, f.read()) for f in debinder_files]
                df_recorder = parse_nb1_debinder_csv(files_data)
                rec_y_cols = [c for c in df_recorder.columns if "Zone #" in c]

        if df_recorder.empty:
            st.error("❌ ไม่สามารถอ่านข้อมูลจากไฟล์ Recorder ได้ กรุณาตรวจสอบความถูกต้องของไฟล์")
        else:
            rec_start = df_recorder["DateTime"].min()
            rec_end = df_recorder["DateTime"].max()
            
            # 4. ตรวจสอบว่าเวลาของ PAQ อยู่ในช่วงของ Recorder หรือไม่
            if paq_start >= rec_start and paq_end <= rec_end:
                st.success(f"✅ วันและเวลาของ PAQ ({paq_start.strftime('%H:%M')}) อยู่ในช่วงข้อมูลของ Recorder (นำกราฟซ้อนกันได้)")
                
                fig = go.Figure()
                
                # --- กราฟ Recorder (เป็นพื้นหลัง/อ้างอิง) ---
                for col in rec_y_cols:
                    fig.add_trace(go.Scatter(x=df_recorder["DateTime"], y=df_recorder[col], name=f"REC: {col}", line=dict(dash='dot', width=1.5), opacity=0.5))
                
                # --- กราฟ PAQ (ซ้อนทับตามเวลาจริง) ---
                for col in probe_cols:
                    fig.add_trace(go.Scatter(x=df_paq["Real_DateTime"], y=df_paq[col], name=f"PAQ: {col}", line=dict(color=PROBE_COLORS.get(col), width=2.5)))
                
                fig.update_layout(
                    title=f"TIMELINE SYNC: PAQ + {furnace_id} Recorder",
                    hovermode="x unified",
                    height=650,
                    xaxis=dict(title="Real Date & Time", type="date", range=[paq_start - timedelta(minutes=5), paq_end + timedelta(minutes=5)]),
                    yaxis=dict(title="Temperature (°C)")
                )
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.error(f"⚠️ คำเตือน: วัน/เวลาของไฟล์ PAQ ({paq_start.strftime('%Y-%m-%d %H:%M:%S')}) \n"
                         f"ไม่อยู่ในช่วงข้อมูล Recorder ({rec_start.strftime('%Y-%m-%d %H:%M:%S')} ถึง {rec_end.strftime('%Y-%m-%d %H:%M:%S')})")
                st.info("👉 **กรุณาอัปโหลดไฟล์ Recorder ชุดใหม่ให้ตรงกับช่วงเวลาที่รัน PAQ** หรือปรับตั้งเวลาเริ่ม PAQ ใหม่ที่เมนู 'Align PAQ Time' ด้านซ้าย")

with tabs[1]:
    st.subheader(f"Global Furnace Profile (Standalone) - {f_variant}")
    fig_orig = go.Figure()
    for col in probe_cols:
        fig_orig.add_trace(go.Scatter(x=df_paq["Time_Seconds"], y=df_paq[col], name=col, line=dict(color=PROBE_COLORS.get(col))))
    fig_orig.update_layout(title=f"Original PAQ Profile: {data_paq['filename']}", xaxis_title="Time (Seconds)", yaxis_title="Temperature (°C)", height=500, hovermode="x unified")
    st.plotly_chart(fig_orig, use_container_width=True)
