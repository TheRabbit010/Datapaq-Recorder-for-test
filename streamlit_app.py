import io
import os
import re
import struct
import zlib
import numpy as np
import olefile
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

# ==============================================================================
# STREAMLIT PAGE CONFIGURATION & CSS STYLING
# ==============================================================================
st.set_page_config(page_title="Datapaq .PAQ Analyzer & Furnace Profiler", page_icon="🔥", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
div[data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 700 !important; white-space: normal !important; line-height: 1.2 !important; }
div[data-testid="stMetricLabel"] { font-size: 1.1rem !important; font-weight: 500 !important; color: #a0aab2 !important; }
div.stButton > button:first-child { background-color: #ff4b4b; color: white; font-weight: bold; border-radius: 5px; width: 100%; margin-bottom: 20px; }
div.stButton > button:first-child:hover { background-color: #ff3333; border-color: #ff3333; }
button[data-baseweb="tab"] { font-size: 1.2rem !important; font-weight: 600 !important; }
div[data-testid="stAlert"] { font-size: 1.3rem !important; font-weight: 500 !important; padding: 1rem !important; }
</style>
""", unsafe_allow_html=True)

PROBE_COLORS = {"PB#1": "#ff0000", "PB#2": "#00ff00", "PB#3": "#0000ff", "PB#4": "#8b4513", "PB#5": "#ff00ff", "PB#6": "#b8860b", "PB#7": "#800080", "PB#8": "#00ffff", "PB#9": "#d32f2f", "PB#10": "#5c4033"}
GROUP_COLORS = {"Dryer": "rgba(255, 235, 156, 0.15)", "Debinder": "rgba(255, 199, 119, 0.15)", "Heating": "rgba(255, 160, 160, 0.15)", "Cooling": "rgba(173, 216, 230, 0.15)"}

STANDARD_SPECS = {
    "NB1 (RAD)": {"id": "PRCNVR02044 Rev C", "max": "Dryer: 175-260°C &nbsp;|&nbsp; Debinder: 200-375°C &nbsp;|&nbsp; Brazing: 583-607°C", "dwell": "Dryer ≥175°C ≥ 1.00 min &nbsp;|&nbsp; Debinder ≥200°C ≥ 2.00 min &nbsp;|&nbsp; Brazing ≥577°C = 2.30 - 7.00 min, ≥583°C ≥ 2.30 min"},
    "NB1 (CDS/KN9/12SHP)": {"id": "PRCNVR02004 Rev.E + 2025 DSR TDOC_101182039 CDS BRAZING CYCLE", "max": "Dryer: 200-350°C &nbsp;|&nbsp; Debinder: 300-375°C &nbsp;|&nbsp; Brazing: 585-607°C", "dwell": "Dryer ≥200°C ≥ 1.30 min &nbsp;|&nbsp; Debinder ≥300°C ≥ 2.30 min &nbsp;|&nbsp; Brazing ≥577°C = 4.00 - 7.45 min (PB#1, PB#5) / 2.00 - 7.45 min (Others)"},
    "NB3 (KE8 : M2/EVO)": {"id": "PRCNVR02059 + V-PAS/T88/Chon Buri 1/2025-10-29-ZVK (Evaporator M2 ,EVO)", "max": "Dryer: 200-375°C &nbsp;|&nbsp; Brazing: M2 = 595-602°C , EVO = 598-606°C", "dwell": "Dryer ≥200°C ≥ 1.30 min &nbsp;|&nbsp; Brazing ≥550°C = 7.00 - 10.30 min, ≥577°C = 4.30 - 7.00 min, ≥591°C = 1.30 - 4.00 min"},
    "NB2 (Tahc)": {"id": "PRCNVR02050 Rev B", "max": "Dryer: 200-375°C &nbsp;|&nbsp; Brazing: 596-604°C", "dwell": "Dryer ≥250°C ≥ 1.00 min &nbsp;|&nbsp; Brazing ≥577°C = 4.00 - 7.00 min, ≥591°C = 1.30 - 4.30 min"},
    "NB2 (Utahc)": {"id": "PRCNVR02050 Rev B + internal control", "max": "Dryer: 200-375°C &nbsp;|&nbsp; Brazing: 596-606°C", "dwell": "Dryer ≥250°C ≥ 1.00 min &nbsp;|&nbsp; Brazing ≥577°C = 4.00 - 7.00 min, ≥591°C = 1.30 - 4.30 min"},
    "NB3 (BTM)": {"id": "PRCNVR02033 Rev C", "max": "Dryer: 300-375°C &nbsp;|&nbsp; Brazing: 595-608°C", "dwell": "Dryer ≥300°C ≥ 2.00 min &nbsp;|&nbsp; Brazing ≥577°C = 4.00 - 14.00 min, ≥591°C = 2.00 - 12.00 min, ≥600°C ≤ 8.00 min"}
}

VALIDATION_RULES = {
    "NB1 (RAD)": {"Dryer Max (°C)": (175, 260), "Debinder Max (°C)": (200, 375), "Brazing Max (°C)": (583, 607), "Dryer Dwell (≥175°C)": (60, 99999), "Debinder Dwell (≥200°C)": (120, 99999), "Brazing Dwell (≥577°C)": (150, 420), "Brazing Dwell (≥583°C)": (150, 99999)},
    "NB1 (CDS/KN9/12SHP)": {"Dryer Max (°C)": (200, 350), "Debinder Max (°C)": (300, 375), "Brazing Max (°C)": (585, 607), "Dryer Dwell (≥200°C)": (90, 99999), "Debinder Dwell (≥300°C)": (150, 99999), "Brazing Dwell (≥577°C)": (120, 465)},
    "NB3 (KE8 : M2/EVO)": {"Dryer Max (°C)": (200, 375), "Brazing Max (°C)": (595, 606), "Dryer Dwell (≥200°C)": (90, 99999), "Brazing Dwell (≥550°C)": (420, 630), "Brazing Dwell (≥577°C)": (270, 420), "Brazing Dwell (≥591°C)": (90, 240)},
    "NB2 (Tahc)": {"Dryer Max (°C)": (200, 375), "Brazing Max (°C)": (596, 604), "Dryer Dwell (≥250°C)": (60, 99999), "Brazing Dwell (≥577°C)": (240, 420), "Brazing Dwell (≥591°C)": (90, 270)},
    "NB2 (Utahc)": {"Dryer Max (°C)": (200, 375), "Brazing Max (°C)": (596, 606), "Dryer Dwell (≥250°C)": (60, 99999), "Brazing Dwell (≥577°C)": (240, 420), "Brazing Dwell (≥591°C)": (90, 270)},
    "NB3 (BTM)": {"Dryer Max (°C)": (300, 375), "Brazing Max (°C)": (595, 608), "Dryer Dwell (≥300°C)": (120, 99999), "Brazing Dwell (≥577°C)": (240, 840), "Brazing Dwell (≥591°C)": (120, 720), "Brazing Dwell (≥600°C)": (0, 480)}
}

def style_inspection_matrix(row, variant, check_dryer_max=False):
    styles = [''] * len(row)
    rules = VALIDATION_RULES.get(variant, {})
    probe_name = row.get("Probe", "")
    
    for i, col in enumerate(row.index):
        if col == "Probe": continue
        val = row[col]
        
        base_bg = ""
        if "Dryer" in col:
            base_bg = "background-color: rgba(255, 235, 156, 0.15);" 
        elif "Debinder" in col:
            base_bg = "background-color: rgba(255, 199, 119, 0.15);" 
        elif "Brazing" in col:
            base_bg = "background-color: rgba(255, 160, 160, 0.15);" 
            
        if val == "***":
            styles[i] = f'{base_bg} color: #f39c12; font-weight: bold; text-align: center;'
            continue

        rule = rules.get(col)
        
        if variant == "NB1 (CDS/KN9/12SHP)" and col == "Brazing Dwell (≥577°C)":
            if probe_name in ["PB#1", "PB#5"]:
                rule = (240, 465)
            else:
                rule = (120, 465)
        
        if not check_dryer_max and ("Dryer Max" in col or "Dryer Dwell" in col):
            rule = None
            
        is_fail = False
        if pd.isna(val) or val == "00:00:00" or val == "" or val == 0 or val == "N/A":
            if rule and rule[0] > 0: is_fail = True
        else:
            if rule:
                min_v, max_v = rule
                if "Max (°C)" in col:
                    try:
                        if not (min_v <= float(val) <= max_v): is_fail = True
                    except: pass
                elif "Dwell" in col:
                    try:
                        parts = str(val).split(':')
                        if len(parts) == 3:
                            total_s = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
                            if not (min_v <= total_s <= max_v): is_fail = True
                    except: pass
                    
        if rule:
            if is_fail: 
                styles[i] = f'background-color: rgba(255, 0, 0, 0.25); color: #d32f2f; font-weight: bold; border: 1px solid #d32f2f;'
            else: 
                styles[i] = f'{base_bg} color: #009900; font-weight: bold;'
        else:
            styles[i] = f'{base_bg}'
            
    return styles

FURNACE_CONFIGS = {
    "NB1": {
        "line_speed_mpm": 1.400, 
        "trigger_temp_brazing": 577.0,
        "zones": [{"num": 1, "name": "Dryer Z#1", "start": 0.00, "length": 3.15, "group": "Dryer"}, {"num": 2, "name": "Dryer Z#2", "start": 3.15, "length": 3.13, "group": "Dryer"}, {"num": 3, "name": "EXT Dryer", "start": 6.27, "length": 0.70, "group": "Dryer"}, {"num": 4, "name": "ENT DB", "start": 6.97, "length": 0.67, "group": "Debinder"}, {"num": 5, "name": "DB Z#1", "start": 7.64, "length": 3.13, "group": "Debinder"}, {"num": 6, "name": "DB Z#2", "start": 10.77, "length": 2.60, "group": "Debinder"}, {"num": 7, "name": "DB Z#3", "start": 13.37, "length": 2.60, "group": "Debinder"}, {"num": 8, "name": "DB Z#4", "start": 15.97, "length": 3.13, "group": "Debinder"}, {"num": 9, "name": "XFER#1", "start": 19.10, "length": 2.71, "group": "Heating"}, {"num": 10, "name": "Z#1", "start": 21.81, "length": 3.14, "group": "Heating"}, {"num": 11, "name": "Z#2", "start": 24.95, "length": 2.68, "group": "Heating"}, {"num": 12, "name": "Z#3", "start": 27.63, "length": 2.72, "group": "Heating"}, {"num": 13, "name": "Z#4", "start": 30.35, "length": 2.04, "group": "Heating"}, {"num": 14, "name": "Z#5", "start": 32.39, "length": 2.00, "group": "Heating"}, {"num": 15, "name": "Z#6", "start": 34.39, "length": 2.00, "group": "Heating"}, {"num": 16, "name": "Z#7", "start": 36.39, "length": 2.29, "group": "Heating"}, {"num": 17, "name": "WatCool#1", "start": 38.68, "length": 2.39, "group": "Cooling"}, {"num": 18, "name": "WatCool#2", "start": 41.07, "length": 1.90, "group": "Cooling"}, {"num": 19, "name": "Exit curtain box", "start": 42.97, "length": 1.90, "group": "Cooling"}, {"num": 20, "name": "XFER#2", "start": 44.87, "length": 0.60, "group": "Cooling"}, {"num": 21, "name": "Air Cool#1", "start": 45.47, "length": 1.25, "group": "Cooling"}, {"num": 22, "name": "Air Cool#2", "start": 46.72, "length": 1.25, "group": "Cooling"}, {"num": 23, "name": "Exit", "start": 47.97, "length": 1.85, "group": "Cooling"}],
        "stages": [{"Stage": "Dryer", "Start (m)": 0.00, "End (m)": 6.28, "thresh": 200.0}, {"Stage": "Debinder", "Start (m)": 7.64, "End (m)": 19.10, "thresh": 300.0}, {"Stage": "Brazing", "Start (m)": 21.81, "End (m)": 42.97, "thresh": 577.0}]
    },
    "NB2": {
        "line_speed_mpm": 1.560, 
        "trigger_temp_brazing": 577.0,
        "zones": [{"num": 1, "name": "DryOff-Z#1", "start": 0.00, "length": 2.80, "group": "Dryer"}, {"num": 2, "name": "DryOff-Z#2", "start": 2.80, "length": 2.80, "group": "Dryer"}, {"num": 3, "name": "Xfer1", "start": 5.60, "length": 3.13, "group": "Dryer"}, {"num": 4, "name": "Z#1", "start": 8.73, "length": 3.60, "group": "Heating"}, {"num": 5, "name": "Z#2", "start": 12.33, "length": 2.70, "group": "Heating"}, {"num": 6, "name": "Z#3", "start": 15.03, "length": 2.40, "group": "Heating"}, {"num": 7, "name": "Z#4", "start": 17.43, "length": 2.10, "group": "Heating"}, {"num": 8, "name": "Z#5", "start": 19.53, "length": 2.30, "group": "Heating"}, {"num": 9, "name": "Z#6", "start": 21.83, "length": 1.90, "group": "Heating"}, {"num": 10, "name": "Z#7", "start": 23.73, "length": 2.20, "group": "Heating"}, {"num": 11, "name": "Xfer2", "start": 25.93, "length": 0.80, "group": "Heating"}, {"num": 12, "name": "Watcol1", "start": 26.73, "length": 1.75, "group": "Cooling"}, {"num": 13, "name": "Watcol2", "start": 28.48, "length": 1.85, "group": "Cooling"}, {"num": 14, "name": "Exit curtain box", "start": 30.33, "length": 2.30, "group": "Cooling"}, {"num": 15, "name": "Airc1", "start": 32.63, "length": 1.25, "group": "Cooling"}, {"num": 16, "name": "Airc2", "start": 33.88, "length": 1.25, "group": "Cooling"}, {"num": 17, "name": "Exit", "start": 35.13, "length": 1.80, "group": "Cooling"}],
        "stages": [{"Stage": "Dryer", "Start (m)": 0.00, "End (m)": 5.60, "thresh": 200.0}, {"Stage": "Brazing", "Start (m)": 8.73, "End (m)": 30.33, "thresh": 577.0}]
    },
    "NB3": {
        "line_speed_mpm": 1.270, 
        "trigger_temp_brazing": 577.0,
        "zones": [{"num": 1, "name": "XFER", "start": 0.00, "length": 0.10, "group": "Dryer"}, {"num": 2, "name": "Dryer#1", "start": 0.10, "length": 1.85, "group": "Dryer"}, {"num": 3, "name": "Dryer#2", "start": 1.95, "length": 1.85, "group": "Dryer"}, {"num": 4, "name": "Dryer#3", "start": 3.80, "length": 1.95, "group": "Dryer"}, {"num": 5, "name": "XFER#1", "start": 5.75, "length": 3.39, "group": "Dryer"}, {"num": 6, "name": "Z#1", "start": 9.14, "length": 3.60, "group": "Heating"}, {"num": 7, "name": "Z#2", "start": 12.74, "length": 2.75, "group": "Heating"}, {"num": 8, "name": "Z#3", "start": 15.49, "length": 2.30, "group": "Heating"}, {"num": 9, "name": "Z#4", "start": 17.79, "length": 2.10, "group": "Heating"}, {"num": 10, "name": "Z#5", "start": 19.89, "length": 2.10, "group": "Heating"}, {"num": 11, "name": "Z#6", "start": 21.99, "length": 1.90, "group": "Heating"}, {"num": 12, "name": "Z#7", "start": 23.89, "length": 1.63, "group": "Heating"}, {"num": 13, "name": "WatCoo#1", "start": 25.52, "length": 2.56, "group": "Cooling"}, {"num": 14, "name": "WatCoo#2", "start": 28.08, "length": 1.90, "group": "Cooling"}, {"num": 15, "name": "Exit curtain box", "start": 29.98, "length": 1.90, "group": "Cooling"}, {"num": 16, "name": "XFER#2", "start": 31.88, "length": 0.60, "group": "Cooling"}, {"num": 17, "name": "AirCoo#1", "start": 32.48, "length": 1.25, "group": "Cooling"}, {"num": 18, "name": "AirCoo#2", "start": 33.73, "length": 1.25, "group": "Cooling"}, {"num": 19, "name": "Exit", "start": 34.98, "length": 1.85, "group": "Cooling"}],
        "stages": [{"Stage": "Dryer", "Start (m)": 0.00, "End (m)": 5.75, "thresh": 200.0}, {"Stage": "Brazing", "Start (m)": 9.14, "End (m)": 29.98, "thresh": 577.0}]
    }
}

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
                    if glitch_count <= 30: 
                        clean_vals.append(clean_vals[-1] if clean_vals else 0.0)
                    else: break
                elif glitch_count > 3: clean_vals = []
        if len(clean_vals) > len(best_series) and max(clean_vals) > 100.0:
            best_series = clean_vals
    return best_series

def format_dwell_time(total_seconds):
    if pd.isna(total_seconds) or total_seconds == 0: return "00:00:00"
    m, s = divmod(total_seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def clean_paq_text(raw_text):
    if not raw_text: return ""
    text = re.split(r'\\\\', raw_text)[0]
    parts = re.split(r'\b(?:CProbe|CSampleInterval|CAxisCustomUnits|CPaqfile|CByteDataArray|CProbeResult|CFurnaceRecipe|CZoom|CProbeMapEntry\w*|cho1-sv|CProcessFile|COven|CZone|CRecipe|CProduct|CAnalysisParameters|CAlarmParameters|CAlarmProbes|CAlarmParametersTime|CRiseFallRange|CTemperatureLimits|CTimeLimits|CCustomUnits|CLineSpeed|COvenStart|CProcessOptimisation|CToleranceCurve|CVersionInfo|CLogger|CSystemInfo|CMaximumMinimumAnalysisParameters|CTimeAtMeasurementAnalysisParameters)\b', text)
    cleaned_parts = []
    for p in parts:
        p = re.sub(r'^[>#;\.,\|]+', '', p).strip() 
        if len(p) < 3: continue
        
        p = re.sub(r'\b(Untitled|Entry Zone|XFER|WatCool|Exit curtain|AirCool|Exit Zone|Dryer#1|VSTS Exit Dryer|Exit Dryer|0Hl|!@f|"onB|aaa\.\.\.|FFGCC|bbbRRR|LNNSQ|OD@)\b', ' ', p, flags=re.IGNORECASE)
        
        is_rec_str = re.search(r'(?i)(During\s*datapaq|O2|WJ|Braze\s*Temp|Top\s*\(|Bot\s*\(|Furnace\s*Parameter|N2\s*Flow|Flux\s*Spray|Frequency\s*motor|NB\s*Top|NB\s*Bot)', p)
        if not is_rec_str:
            if re.search(r'([^\-\/0-9])\1{4,}', p) or re.search(r'[@^\$|~<>{}\[\]]{2,}', p): continue 
        
        p = re.sub(r'#[0-9]{3,}', '', p)
        p = re.sub(r'\s+', ' ', p).strip()
        if p and len(p) >= 3: cleaned_parts.append(p)
    return " ".join(cleaned_parts)

def parse_operator_and_metadata(comments_list):
    combined = " ".join(comments_list)
    op, site = "N/A", "N/A"
    comp = "VSTS"
    
    m_site = re.search(r'(Power\s+Chonburi|Chonburi|Plant\s+\d+|Factory\s+\d+)', combined, re.IGNORECASE)
    if m_site: site = m_site.group(1).strip()
    
    clean_notes = re.sub(r'^\s*CAlarm\s*', '', combined, flags=re.IGNORECASE)
    
    m_op = re.search(r'^([A-Za-z/]+)\s+(?:Datapaq|NB[1-3]|Monthly|WK|date|product|validation|run|test|DBLog|disconnected|Power|Chonburi|Plant|Factory)', clean_notes, re.IGNORECASE)
    if m_op: 
        op = m_op.group(1).strip()
    elif re.search(r'\b(Niwat|Sunisa|Mongkhon|Sompong|Jintana|Operator)\b', clean_notes, re.IGNORECASE):
        op = re.search(r'\b(Niwat|Sunisa|Mongkhon|Sompong|Jintana|Operator)\b', clean_notes, re.IGNORECASE).group(1).strip()

    log_marker = re.search(r'(disconnected:|DBLog Cleared:|DP2300|CommIn:LOGGER_|USB_NOTIFY_|TickRate|VBatt|\(USB_VALID\)|CommsIn\s+\d+|LoggerState_NewState:|trigger_search|DP\d{4}|Logger:|Battery:|Firmware:|Serial No:)', clean_notes, flags=re.IGNORECASE)
    if log_marker:
        clean_notes = clean_notes[:log_marker.start()].strip()
    
    for token in [op, "VSTS", site, "CAlarm"]:
        if token != "N/A":
            clean_notes = re.sub(rf'^[\s\W]*{re.escape(token)}\b[\s\W]*', '', clean_notes, flags=re.IGNORECASE)

    clean_notes = re.sub(r'NB\s+with\s+Debinder\s+NB\s+Furnace\s+Total\s*;\s*[\d,]+\s*mm', '', clean_notes, flags=re.IGNORECASE)
    clean_notes = re.split(r':?\s*NB\s*[1-3]\s*with\s*Debinder', clean_notes, flags=re.IGNORECASE)[0]
    
    chop_pattern = r'\b(NB\s*\d\s*DryOff|DryOff-Z|Xfer2\s*Watcol|Watcol1|AN\s*h8|ljjSQP|xwTLL)\b'
    split_notes = re.split(chop_pattern, clean_notes, flags=re.IGNORECASE)
    if len(split_notes) > 1:
        clean_notes = split_notes[0].strip()
        
    garbage_start = re.search(r'([A-Za-z]\\[A-Za-z]|[\$\#\^\~]{2,}|\?[A-Z]{2,}|[a-z]{2,}\~|\bKO\\|\b\d{1,2}:\d{1,2}[A-Z]+)', clean_notes)
    if garbage_start:
        clean_notes = clean_notes[:garbage_start.start()]
        
    garbage_regex = r'(C:\\Program Files|IJ@1|a@FGr|YW@\.|dhmquz|QUZ|rx\s+knv|V\^e|ipyw~|MSYmqw~|AFMEKO|FIL257|CVersionInfo|1w-!|zfo@|8gDi|R@\?m|MQTDFI|HKN\*,|Double m\b|double m\b)'
    clean_notes = re.split(garbage_regex, clean_notes, flags=re.IGNORECASE)[0]
    
    clean_notes = re.sub(r'(?i)\b[a-z]:\\[^\s]*', '', clean_notes)
    clean_notes = re.sub(r'(?i)https?://[^\s]*', '', clean_notes)
    clean_notes = re.sub(r'(?i)\\\\[a-z0-9_]+\\[^\s]*', '', clean_notes)
    
    clean_notes = re.sub(r'[^\w\s\.\,\-\/\(\)\=\+:\%\*]', ' ', clean_notes)
    clean_notes = re.sub(r'\b[A-Z0-9]{15,}\b', '', clean_notes) 
    
    for token in [comp, site]:
        if token != "N/A":
            clean_notes = re.sub(rf'\b{re.escape(token)}\b', '', clean_notes, flags=re.IGNORECASE)
            
    extra_probes = []
    probe_matches = re.finditer(r'(?:Probe\s*no\.?\s*(?:[1-9]|10)|PB#(?:[1-9]|10)|#(?:[1-9]|10)\s*\().*?(?=\Z|\bProbe\s*no|\bPB#|#(?:[1-9]|10)\s*\()', clean_notes, flags=re.IGNORECASE)
    for m in probe_matches:
        p_text = m.group(0).strip()
        if re.search(r'(core|bottom|top|left|right|manifold|pipe|drill)', p_text, re.IGNORECASE):
            extra_probes.append(p_text)
            
    loc_cutoff = re.search(r'\b(Bottom\s*-\s*(Top|Bottom|Center|Left|Right)|Top\s*-\s*(Top|Bottom|Center|Left|Right)|Middle\s*left|Middle\s*right|Right\s*core|Left\s*core|NB\s*\d\s*with\s*Debinder|Dryer\s*Z\s*1)\b', clean_notes, re.IGNORECASE)
    if loc_cutoff:
        clean_notes = clean_notes[:loc_cutoff.start()]
        
    clean_notes = re.sub(r'\b(hzgxdvN|ljjSQP|xwTLL|nif\s*jgni)\b', '', clean_notes, flags=re.IGNORECASE)
    clean_notes = re.sub(r'\s:\s(?=[A-Za-z])', ' ', clean_notes)
    
    clean_notes = re.sub(r'\s{2,}', ' ', clean_notes)
    clean_notes = re.sub(r'^[.,;\s:]+', '', clean_notes)
    clean_notes = re.sub(r'[\.,\s]+$', '.', clean_notes).strip()
    
    return op, comp, site, clean_notes if clean_notes else "N/A", extra_probes

def clean_probe_location(loc_desc):
    loc_desc = re.sub(r'^[^A-Za-z]*(Top|Bottom|Middle|Left|Right|Core)', r'\1', loc_desc, flags=re.IGNORECASE)
    return re.sub(r'\b[A-Z](Left|Right|Middle|Bottom|Top)\b', r'\1', loc_desc, flags=re.IGNORECASE)

@st.cache_data
def process_paq_file(file_bytes, filename):
    ole_bytes = io.BytesIO(file_bytes)
    ole = olefile.OleFileIO(ole_bytes)
    
    raw_texts = []
    embedded_img = None
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
            if embedded_img is None and len(data_b) > 500:
                for header in [b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'BM']:
                    idx = data_b.find(header)
                    if idx != -1:
                        try:
                            embedded_img = Image.open(io.BytesIO(data_b[idx:]))
                            break
                        except: pass
            ascii_matches = re.findall(rb'[\x20-\x7E]{4,}', data_b)
            for m in ascii_matches: raw_texts.append(m.decode('ascii', errors='ignore').strip())
        except: continue

    channel_mapping = {}
    num_logger_channels = 0
    for s in raw_texts:
        matches = re.findall(r'#probe\s+number\s+#(\d+)\s*=\s*(\d+)', s, re.IGNORECASE)
        for m in matches:
            channel_mapping[int(m[0])] = int(m[1])
            
        if num_logger_channels == 0:
            m_ch = re.search(r'#number of channels\s*=\s*(\d+)', s, re.IGNORECASE)
            if m_ch:
                num_logger_channels = int(m_ch.group(1))

    if num_logger_channels == 0:
        num_logger_channels = max(channel_mapping.values()) if channel_mapping else 10
        
    num_logger_channels = min(num_logger_channels, 10) 

    probe_streams = [s for s in ole.listdir() if len(s) >= 4 and s[0] == 'Paqfiles' and s[2] == 'ProbeResults']
    probe_streams = sorted(probe_streams, key=lambda x: x[-1])

    all_probes = {}
    for idx, stream_path in enumerate(probe_streams):
        stream_name = "/".join(stream_path)
        internal_idx = idx + 1
        physical_ch = channel_mapping.get(internal_idx, internal_idx)
        col_name = f"PB#{physical_ch}"
        
        d = decompress_stream(ole, stream_name)
        if d:
            series = extract_probe_series_autonomously(d)
            if series: all_probes[col_name] = series

    max_samples = max(len(v) for v in all_probes.values()) if all_probes else 0
    if max_samples == 0: return None

    aligned_probes = {k: (v + [np.nan] * (max_samples - len(v)) if len(v) < max_samples else v) for k, v in all_probes.items()}
    df_master = pd.DataFrame(aligned_probes)
    df_master.insert(0, "Time_Seconds", range(len(df_master)))
    base_date = pd.Timestamp("1970-01-01 00:00:00")
    df_master.insert(1, "Time_Stamp", base_date + pd.to_timedelta(df_master["Time_Seconds"], unit="s"))
    df_master.insert(2, "Time_HHMMSS", df_master["Time_Stamp"].dt.strftime('%H:%M:%S'))

    expected_cols = [f"PB#{i}" for i in range(1, 11)]
    for col in expected_cols:
        if col not in df_master.columns:
            df_master[col] = np.nan

    probe_cols = expected_cols
    invalid_cols = []
    
    for col in probe_cols:
        series = df_master[col].dropna()
        if len(series) == 0:
            invalid_cols.append(col)
            continue
        if len(series) < len(df_master) * 0.20:
            invalid_cols.append(col)
            df_master[col] = np.nan
            continue
        if series.max() < 100.0:
            invalid_cols.append(col)
            df_master[col] = np.nan
            continue
            
    if not [c for c in probe_cols if c not in invalid_cols]: return None 
    
    SUSTAINED_SECONDS = 15
    probe_start_secs = {}
    for col in probe_cols:
        is_p60 = (df_master[col] >= 60.0)
        valid_p_mask = is_p60.copy()
        for i in range(1, SUSTAINED_SECONDS):
            valid_p_mask = valid_p_mask & is_p60.shift(-i, fill_value=False)
        probe_start_secs[col] = int(df_master[valid_p_mask].iloc[0]["Time_Seconds"]) if valid_p_mask.any() else 0

    valid_starts = [sec for sec in probe_start_secs.values() if sec > 0]
    detected_start_sec = min(valid_starts) if valid_starts else 0
    if valid_starts:
        first_probe_name = [k for k, v in probe_start_secs.items() if v == detected_start_sec][0]
    else:
        valid_p = [c for c in probe_cols if c not in invalid_cols]
        first_probe_name = valid_p[0] if valid_p else probe_cols[0]

    detected_start_hhmmss = df_master[df_master["Time_Seconds"] == detected_start_sec].iloc[0]["Time_HHMMSS"]

    found_comments, found_recipes, found_probes = [], [], []
    for s in raw_texts:
        if re.search(r'\\\\|\b[A-Z]:\\', s) or re.search(r'\.(ovn|prd|pro|rec|paq|jpg|png|bmp)\b', s, re.IGNORECASE) or re.search(r'\\Users\\|Desktop', s, re.IGNORECASE): continue
        s_clean = clean_paq_text(s)
        if not s_clean: continue

        is_probe = re.search(r'\b(cooler|drill&insert|inside H/D|manifold|core|PB#\d|Probe\s*no|Left\s*core|Right\s*core|Middle\s*core)\b', s_clean, re.IGNORECASE)
        is_note = re.search(r'\b(validation|product|new bar|WK\d|Loaded|Model|week\d|date\d|datapaq|spacer|gap|EVO|G100|Tahc)\b', s_clean, re.IGNORECASE)
        
        if is_probe and not is_note and len(s_clean) < 80:
            if s_clean not in found_probes: found_probes.append(s_clean)
        else:
            is_recipe = re.search(r"(?i)(During\s*datapaq|Furnace\s*Parameter|O2\s*Exit|ppm|CV\s*speed|Braze\s*Temp|Top\s*\(\'?C\'?\)|Bot\s*\(\'?C\'?\)|Top\s*:|Bot\s*:|Temp\s*Top|Temp\s*Bot|N2\s*Flow|WJ\s*Flow|Flux\s*Spray|NB\s*Top|NB\s*Bot|Frequency\s*motor)", s_clean)
            if is_recipe and re.search(r'(apply\s*flux|paste\s*flux|nocolok|loading\s*double|gap\s*\d+mm)', s_clean, re.IGNORECASE) and not re.search(r'(during\s*datapaq|WJ\s*Flow|Braze\s*Temp|Top\s*\()', s_clean, re.IGNORECASE):
                is_recipe = False
                
            if is_recipe:
                s_rec = s_clean
                note_part = ""
                match_during = re.search(r'(?i)(?:data\s*)?during\s*datapaq', s_rec)
                if match_during:
                    note_part = s_rec[:match_during.start()].strip()
                    s_rec = "Data during datapaq " + s_rec[match_during.end():]
                else:
                    match_recipe_start = re.search(r"(?i)(Furnace\s*Parameter|O2|N2\s*Flow|WJ|CV\s*speed|Braze\s*Temp|Top\s*\(\'?C\'?\)|Bot\s*\(\'?C\'?\)|Top\s*:|Bot\s*:|NB\s*Top|NB\s*Bot)", s_rec)
                    if match_recipe_start:
                        note_part = s_rec[:match_recipe_start.start()].strip()
                        s_rec = s_rec[match_recipe_start.start():]
                    else:
                        note_part = s_rec 

                if note_part and note_part not in found_comments: found_comments.append(note_part)
                
                s_rec = re.sub(r'[\{\}\[\]\^\`\\]+', '', s_rec) 
                s_rec = re.sub(r'\b(?:CProcessFile|COven|CZone|CRecipe|CProduct|CAnalysisParameters|CToleranceCurve|CAlarmParametersDouble|CMaximumMinimumAnalysisParameters|CTimeAtMeasurementAnalysisParameters|CRiseFallAnalysisParameters|CSlopeAnalysisParameters|CPeakDifferenceAnalysisParameters|CAreaUnderCurveAnalysisParameters|CFurnaceSurveyAnalysisParameters)\b', '', s_rec).strip()
                s_rec = re.sub(r'cer<>Hz\}', '', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'==\?mnojjo[^\s]+', '', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(N2\s*Flow=?)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Flux\s*Spray)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Frequency\s*motor)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(WJ Flow)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(NB Top Temp)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(NB Bot temp)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(NB\s*Top\s*Temp\s*:?)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(NB\s*Bot\s*temp\s*:?)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Braze\s*Temp:?)', r'\n\1 ', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(BrazeTemp:?)', r'\n\1 ', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Brazed temp:?)', r'\n\1 ', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Brazing temp:?)', r'\n\1 ', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r"(Top\s*\(\'?C\'?\)\s*:?)", r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r"(Bot\s*\(\'?C\'?\)\s*:?)", r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Temp\s*Top\s*:?)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'(Temp\s*Bot\s*:?)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'\b(Top\s*:)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r'\b(Bot\s*:)', r'\n\1', s_rec, flags=re.IGNORECASE)
                s_rec = re.sub(r' +', ' ', s_rec)
                s_rec = re.sub(r'\n\s+', '\n', s_rec)
                s_rec = re.sub(r'\n{2,}', '\n', s_rec).strip()
                if s_rec and s_rec not in found_recipes and s_rec != note_part: found_recipes.append(s_rec)
            else:
                if s_clean not in found_comments: found_comments.append(s_clean)

    operator_name, company, site, clean_comments_text, extra_probes = parse_operator_and_metadata(found_comments)
    
    valid_probes = []
    for p in found_probes + extra_probes:
        if re.search(r'\b(DryOff|Xfer|Watcol|AirC|Exit curtain|AN h8|ljjSQP|xwTLL|ZY\+|nif jgni|Exit)\b', p, re.IGNORECASE): continue
        valid_probes.append(p)

    probe_locations = {}
    unassigned_probes = []
    
    def clean_global_garbage(text):
        if not text or text == "N/A": return text
        text = re.sub(r'^[\s\W]*;>=ced\b\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^[\s\W]*;>=ced', '', text, flags=re.IGNORECASE) 
        text = re.sub(r'^[\s\W]*;>=[a-z]+\s*', '', text) 
        text = re.sub(r'^[\s\W]*(Niwat|Sunisa|Mongkhon|Sompong|Jintana|Operator)\b[\s\W]*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'[a-zA-Z_]{20,}~?', '', text) 
        text = re.sub(r'(?:[A-Z]{3,}==;|SRQBB)[^\n]*', '', text)
        text = re.sub(r'([3]{4,}[a-zA-Z\s]+)+[3]{4,}[^\n]*', '', text) 
        text = re.sub(r'[,H\s]*3{3,}[\sN,3a-zA-Z]*', '', text) 
        text = re.sub(r'\s*(\b\d{1,2}[a-zA-Z]?\s+\d{4,}\s+)?(3{6,}|2{6,}|1{6,}|0{6,}|\b\d{6,}\s+\d{6,})[^\n]*', '', text)
        garbage_match = re.search(r'([a-zA-Z])\1{4,}|([a-zA-Z]{2})\2{3,}|RSS\s+SS\s+SSS|SsSZ\)|Iapcd\s+iegg|PuSu\s+Yuuu|aucucu\s+luku|\bJsK\s+MQsQ|\bQYSsS\b|\bWiiolpqr\b|\bvuAuu\b|EQUdcgcfZadWaXY', text)
        if garbage_match: text = text[:garbage_match.start()]
        text = re.sub(r'[\s\.\,\-]+(?:24275|\d{4,6})\s*$', '', text) 
        text = re.sub(r'[\s,;:.\-\&\#\$\!\(\)\*\+]+$', '', text).strip()
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text if text else "N/A"

    temp_combined_probes = " ".join(valid_probes)
    clean_comments_text = clean_global_garbage(clean_comments_text)
    
    process_settings = clean_global_garbage("\n".join(found_recipes) if found_recipes else "Standard Recipe Parameters")
    process_settings = re.sub(r'\n{3,}', '\n\n', process_settings).strip()

    recipe_corpus = f"{process_settings} {clean_comments_text} {filename} {temp_combined_probes}"

    # FURNACE IDENTIFICATION
    furnace_id, furnace_variant = "NB3", "NB3"
    if re.search(r'\bRAD\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB1", "NB1 (RAD)"
    elif re.search(r'\b(Utahc|UT)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB2", "NB2 (Utahc)"
    elif re.search(r'\b(Tahc|G2|NB2)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB2", "NB2 (Tahc)"
    elif re.search(r'\b(CDS|KN9|12SHP|DNGA|P42QR|P42V|SU2|F44|Y4L)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB1", "NB1 (CDS/KN9/12SHP)"
    elif re.search(r'\bBTM\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB3", "NB3 (BTM)"
    elif re.search(r'\b(KE8|M2|EVO|NB3)\b', recipe_corpus, re.IGNORECASE): furnace_id, furnace_variant = "NB3", "NB3 (KE8 : M2/EVO)"
    elif (re.search(r'\bWK\d{1,2}\b', recipe_corpus, re.IGNORECASE) or re.search(r'\b\d{6}\b', recipe_corpus)): furnace_id, furnace_variant = "NB1", "NB1 (Standard)"
    else:
        f_match = re.search(r'NB\s*Furnace\s*0?([123])\b|NB\s*#?\s*0?([123])\b|NB-0?([123])\b', recipe_corpus, re.IGNORECASE)
        if f_match: 
            found_num = next(g for g in f_match.groups() if g is not None)
            furnace_id = furnace_variant = f"NB{found_num}"
            
    is_j4ll = bool(re.search(r'\b(J4LL)\b', recipe_corpus, re.IGNORECASE))

    if not (is_j4ll and "NB3 (KE8 : M2/EVO)" in furnace_variant):
        for col in ["PB#9", "PB#10"]:
            if col in invalid_cols:
                if col in probe_cols: probe_cols.remove(col)
                invalid_cols.remove(col)
                if col in df_master.columns: df_master.drop(columns=[col], inplace=True)

    if "NB1 (CDS" in furnace_variant:
        CDS_MODELS_PROBES = {
            "F44": {
                "PB#1": "#1 (°C) Bottom core - Middle center drill inside T25.",
                "PB#2": "#2 (°C) Bottom core - Top right drill inside T7 far mani 8-15mm.",
                "PB#3": "#3 (°C) Bottom core - Bot right drill end cap RD 1.5-2mm.",
                "PB#4": "#4 (°C) Bottom core - Bot left drill inside inlet block 2-4mm. far cov2-3mm.",
                "PB#5": "#5 (°C) Top core - Middle center drill inside T25.",
                "PB#6": "#6 (°C) Top core - Bot left drill inside T7 far mani 8-15mm.",
                "PB#7": "#7 (°C) Top core - Top left drill end cap RD 1.5-2mm.",
                "PB#8": "#8 (°C) Top core - Top right drill inside inlet block 2-4mm. far cov2-3mm."
            },
            "DNGA": {
                "PB#1": "#1 (°C) Bot core-Middle center/drill inside T26.",
                "PB#2": "#2 (°C) Bot core-Top right/drill inside T19/far mani 10mm.",
                "PB#3": "#3 (°C) Bot core-Bottom right/drill end capRD 2mm.",
                "PB#4": "#4 (°C) Bot core-Top left/drill inlet block/far cov1mm.",
                "PB#5": "#5 (°C) Top core-Middle center/drill inside T26.",
                "PB#6": "#6 (°C) Top core-Bottom left/drill inside T19/far mani 10mm.",
                "PB#7": "#7 (°C) Top core-Top left/drill end capRD 2mm.",
                "PB#8": "#8 (°C) Top core-Bottom right/drill inlet block/far cov1mm."
            },
            "D12A": {
                "PB#1": "#1 (°C) Front core - Top-left position, inserted into SubCool, near T4, 1-2 mm away from the cover.",
                "PB#2": "#2 (°C) Front core - Top-right position, inserted into SmallCon, near T3, 8-12 mm away from the cover.",
                "PB#3": "#3 (°C) Front core - Bottom-right position, inserted into BigCon, near T9, 8-12 mm away from the cover.",
                "PB#4": "#4 (°C) Front core - Core center position, inserted into tube fin No. 15.",
                "PB#5": "#5 (°C) Rear core - Top-left position, inserted into SubCool, near T4, 1-2 mm away from the cover.",
                "PB#6": "#6 (°C) Rear core - Top-right position, inserted into SmallCon, near T3, 8-12 mm away from the cover.",
                "PB#7": "#7 (°C) Rear core - Bottom-right position, inserted into BigCon, near T9, 8-12 mm away from the cover.",
                "PB#8": "#8 (°C) Rear core - Core center position, inserted into tube fin No. 15."
            },
            "P42QR": {
                "PB#1": "#1 (°C) Bottom - Center core / inside T32.",
                "PB#2": "#2 (°C) Bottom - Bottom left / inside T25 / far mani manifold 7mm.",
                "PB#3": "#3 (°C) Bottom - Top left / insideT1 / far manifold 7mm.",
                "PB#4": "#4 (°C) Bottom - Top right / drill inside block 3mm. / far cover5mm.",
                "PB#5": "#5 (°C) Top - Center core / inside T32.",
                "PB#6": "#6 (°C) Top - Top right / inside T25 / far mani manifold 7mm.",
                "PB#7": "#7 (°C) Top - Bottom right / insideT1 / far manifold 7mm.",
                "PB#8": "#8 (°C) Top - Bottom left / drill inside block 3mm. / far cover5mm."
            },
            "CE": {
                "PB#1": "#1 (°C) Bot-mid center drill inside tube24.",
                "PB#2": "#2 (°C) Bot-bot right drill inside tube6 far mani 7mm.",
                "PB#3": "#3 (°C) Bot-top right drill inside tube1 far mani 7mm.",
                "PB#4": "#4 (°C) Bot-top left drill inlet block 5mm. far cover 5mm.",
                "PB#5": "#5 (°C) Top-mid center drill inside tube24.",
                "PB#6": "#6 (°C) Top-bot right drill inside tube6 far mani 7mm.",
                "PB#7": "#7 (°C) Top-top right drill inside tube1 far mani 7mm.",
                "PB#8": "#8 (°C) Top-bot left drill inlet block 5mm. far cover 5mm."
            },
            "SU2": {
                "PB#1": "#1 (°C) Bottom - Middle center drill inside tube25.",
                "PB#2": "#2 (°C) Bottom - Bottom left drill inside tube8 far mani 7-15mm.",
                "PB#3": "#3 (°C) Bottom - Drill inside end cap RD 1.5-2mm.",
                "PB#4": "#4 (°C) Bottom - Top right drill inside center of I/O block 2-4mm. far cov 1mm.",
                "PB#5": "#5 (°C) Top - Middle center drill inside tube25.",
                "PB#6": "#6 (°C) Top - Top right drill inside tube8 far mani 7-15mm.",
                "PB#7": "#7 (°C) Top - Drill inside end cap RD 1.5-2mm.",
                "PB#8": "#8 (°C) Top - Bottom left drill inside center of I/O block 2-4mm. far cov 1mm."
            },
            "CMFB": {
                "PB#1": "#1 (°C) Bot - Middle center/T27/Drill inside the tube 5mm.",
                "PB#2": "#2 (°C) Bot - Top right/T12/Drill inside the tube 5mm/far mani 7mm.",
                "PB#3": "#3 (°C) Bot - Bot left/Drill in end cap 2mm.",
                "PB#4": "#4 (°C) Bot - Bot left/Drill inlet block 5mm/far cover 5mm.",
                "PB#5": "#5 (°C) Top - Middle center/T27/Drill inside the tube 5mm.",
                "PB#6": "#6 (°C) Top - Bot left/T12/Drill inside the tube 5mm/far mani 7mm.",
                "PB#7": "#7 (°C) Top - Drill in end cap 2mm.",
                "PB#8": "#8 (°C) Top - Top right/Drill inlet block 5mm/far cover5mm."
            },
            "Y4L": {
                "PB#1": "#1 (°C) Bot core - Bot right,drill OutletCon nearT6,far cov1-2mm.",
                "PB#2": "#2 (°C) Bot core - Bot left,drill onPipe nearT6,far cov1-2mm.",
                "PB#3": "#3 (°C) Bot core - Top right,drill SubCool nearT7,far cov1-2mm.",
                "PB#4": "#4 (°C) Bot core - Mid center,drill inside T23.",
                "PB#5": "#5 (°C) Top core - Bot right,drill OutletCon nearT6,far cov1-2mm.",
                "PB#6": "#6 (°C) Top core - Bot left,drill onPipe nearT6,far cov1-2mm.",
                "PB#7": "#7 (°C) Top core - Top right,drill SubCool nearT7,far cov1-2mm.",
                "PB#8": "#8 (°C) Top core - Mid center,drill inside T23."
            },
            "MY25": {
                "PB#1": "#1 (°C) Bot core-Middle center/drill inside T28.",
                "PB#2": "#2 (°C) Bot core-Bottom right/drill inside T10/far mani 10mm.",
                "PB#3": "#3 (°C) Top core-Top right/drill end capRD 1.5-2mm.",
                "PB#4": "#4 (°C) Top core-Middle left/drill inlet&outlet block2-3mm/far cov1mm.",
                "PB#5": "#5 (°C) Top core-Middle center/drill inside T28.",
                "PB#6": "#6 (°C) Bot core-Collar+Hole/Bottom right/drill inside T10/far mani 10mm.",
                "PB#7": "#7 (°C) Top core-Bottom right/drill end capRD 1.5-2mm.",
                "PB#8": "#8 (°C) Top core-/Middle left/drill inlet&outlet block2-3mm/far cov1mm."
            }
        }
        
        combined_text_for_search = temp_combined_probes + " " + clean_comments_text
        detected_model = None
        for model in CDS_MODELS_PROBES.keys():
            if re.search(rf'\b{model}\b', combined_text_for_search, re.IGNORECASE):
                detected_model = model
                break
                
        if not detected_model: detected_model = "P42QR" 
        default_cds = CDS_MODELS_PROBES[detected_model]
        
        max_cds_pb = max([int(c.replace("PB#","")) for c in probe_cols] + [8])
        for i in range(1, max_cds_pb + 1): 
            k = f"PB#{i}"
            if k in default_cds:
                probe_locations[k] = default_cds[k]
            else:
                if i <= 8 or k in probe_cols:
                    probe_locations[k] = f"#{i} (°C) Unlabeled"

    else:
        for p in valid_probes:
            m = re.search(r'^(?:#|Probe\s*no\.?\s*|PB#)?([1-9]|10)\s*[\(°C\)]*\s*[-:]?\s*(.+)', p, re.IGNORECASE)
            if m:
                idx = int(m.group(1))
                if 1 <= idx <= 10:
                    ch_key = f"PB#{idx}"
                    loc_desc = clean_probe_location(m.group(2).strip())
                    label = f"#{idx} (°C) {loc_desc}"
                    if ch_key not in probe_locations or len(label) > len(probe_locations.get(ch_key, "")):
                        probe_locations[ch_key] = label
                else:
                    unassigned_probes.append(p)
            else:
                unassigned_probes.append(p)
                
        if "NB2" in furnace_variant:
            nb2_standard_mapping = {
                "PB#1": "#1 (°C) Left core - Bottom left touch F/T2 far H/D 7-10mm.",
                "PB#2": "#2 (°C) Left core - Top right touch F/T2 far H/D 7-10mm.",
                "PB#3": "#3 (°C) Middle left core - Bottom left touch F/T2 far H/D 7-10mm.",
                "PB#4": "#4 (°C) Middle left core - Top right touch F/T2 far H/D 7-10mm.",
                "PB#5": "#5 (°C) Middle right core - Bottom left touch F/T2 far H/D 7-10mm.",
                "PB#6": "#6 (°C) Middle right core - Top right touch F/T2 far H/D 7-10mm.",
                "PB#7": "#7 (°C) Right core - Bottom left touch F/T2 far H/D 7-10mm.",
                "PB#8": "#8 (°C) Right core - Top right touch F/T2 far H/D 7-10mm."
            }
            for pb, correct_label in nb2_standard_mapping.items():
                if pb in probe_cols:
                    probe_locations[pb] = correct_label
                    
        if "NB1 (RAD)" in furnace_variant:
            nb1_rad_mapping = {
                "PB#1": "#1 (°C) Bottom core - Bottom right drill inside layer tube1.",
                "PB#2": "#2 (°C) Bottom core - Middle center drill inside tube34.",
                "PB#3": "#3 (°C) Bottom core - Top left drill inside layer tube1.",
                "PB#8": "#8 (°C) Bottom core - Top right drill inside layer tube1.",
                "PB#4": "#4 (°C) Top core - Bottom right drill inside layer tube1.",
                "PB#5": "#5 (°C) Top core - Middle center drill inside tube34.",
                "PB#6": "#6 (°C) Top core - Top left drill inside layer tube1.",
                "PB#7": "#7 (°C) Top core - Bottom left drill inside layer tube1."
            }
            for pb, correct_label in nb1_rad_mapping.items():
                if pb in probe_cols:
                    probe_locations[pb] = correct_label
                    
        if is_j4ll and "NB3 (KE8 : M2/EVO)" in furnace_variant:
            nb3_ke8_mapping = {
                "PB#1": "#1 (°C) Right core - Top right F/T1 far tank 5-10mm.",
                "PB#2": "#2 (°C) Right core - Middle center F/T17.",
                "PB#3": "#3 (°C) Right core - Top left F/T1 far tank 5-10mm.",
                "PB#4": "#4 (°C) Right core - Bot left F/T1 far tank 5-10mm.",
                "PB#5": "#5 (°C) Right core - Bot right F/T1 far tank 5-10mm.",
                "PB#6": "#6 (°C) Left core - Top right F/T1 far tank 5-10mm.",
                "PB#7": "#7 (°C) Left core - Middle center F/T17.",
                "PB#8": "#8 (°C) Left core - Top left F/T1 far tank 5-10mm.",
                "PB#9": "#9 (°C) Left core - Bot left F/T1 far tank 5-10mm.",
                "PB#10": "#10 (°C) Left core - Bot right F/T1 far tank 5-10mm."
            }
            for pb, correct_label in nb3_ke8_mapping.items():
                if pb in probe_cols:
                    probe_locations[pb] = correct_label
        
        max_probe_idx = 10 if (is_j4ll and "NB3 (KE8 : M2/EVO)" in furnace_variant) else max([int(c.replace("PB#", "")) for c in probe_cols] + [8])
        
        assigned_idx = 1
        for p in unassigned_probes:
            while f"PB#{assigned_idx}" in probe_locations and assigned_idx <= max_probe_idx: assigned_idx += 1
            if assigned_idx > max_probe_idx: break
            clean_p = re.sub(r'^[0-9]+\s*', '', p)
            probe_locations[f"PB#{assigned_idx}"] = f"#{assigned_idx} (°C) {clean_probe_location(clean_p.strip())}"
            assigned_idx += 1

        for i in range(1, max_probe_idx + 1):
            k = f"PB#{i}"
            if k not in probe_locations:
                if i <= 8 or k in probe_cols:
                    probe_locations[k] = f"#{i} (°C) Unlabeled"

    base_cfg = FURNACE_CONFIGS.get(furnace_id, FURNACE_CONFIGS["NB3"])
    cfg = dict(base_cfg)

    if "RAD" in furnace_variant: cfg.update({"dryer_dwell_thresh_1": 150.0, "dryer_dwell_thresh_2": 175.0, "debinder_dwell_thresh": 200.0, "brazing_dwell_thresh_1": 550.0, "brazing_dwell_thresh_2": 577.0, "brazing_dwell_thresh_3": 583.0, "brazing_dwell_thresh_4": 600.0})
    elif "NB1" in furnace_variant: cfg.update({"dryer_dwell_thresh_1": 150.0, "dryer_dwell_thresh_2": 200.0, "debinder_dwell_thresh": 300.0, "brazing_dwell_thresh_1": 550.0, "brazing_dwell_thresh_2": 577.0, "brazing_dwell_thresh_3": 591.0, "brazing_dwell_thresh_4": 600.0})
    elif "NB2" in furnace_variant: cfg.update({"dryer_dwell_thresh_1": 200.0, "dryer_dwell_thresh_2": 250.0, "debinder_dwell_thresh": None, "brazing_dwell_thresh_1": 550.0, "brazing_dwell_thresh_2": 577.0, "brazing_dwell_thresh_3": 591.0, "brazing_dwell_thresh_4": 600.0})
    elif "BTM" in furnace_variant: cfg.update({"dryer_dwell_thresh_1": 250.0, "dryer_dwell_thresh_2": 300.0, "debinder_dwell_thresh": None, "brazing_dwell_thresh_1": 550.0, "brazing_dwell_thresh_2": 577.0, "brazing_dwell_thresh_3": 591.0, "brazing_dwell_thresh_4": 600.0})
    elif "NB3" in furnace_variant: cfg.update({"dryer_dwell_thresh_1": 150.0, "dryer_dwell_thresh_2": 200.0, "debinder_dwell_thresh": None, "brazing_dwell_thresh_1": 550.0, "brazing_dwell_thresh_2": 577.0, "brazing_dwell_thresh_3": 591.0, "brazing_dwell_thresh_4": 600.0})

    line_speed_mpm = cfg["line_speed_mpm"]
    cv_sp_matches = re.findall(r'CV\s*SP\s*[:=]?\s*(\d{3,4})\s*(?:mm/\s*min|mm)?', recipe_corpus, re.IGNORECASE)
    if cv_sp_matches:
        last_speed = float(cv_sp_matches[-1])
        if 800.0 <= last_speed <= 2500.0: line_speed_mpm = last_speed / 1000.0

    df_master["Distance_Meters"] = ((df_master["Time_Seconds"] - detected_start_sec) / 60.0) * line_speed_mpm
    probe_start_info = {}
    for col in probe_cols:
        p_sec = probe_start_secs[col]
        offset_m = ((p_sec - detected_start_sec) / 60.0) * line_speed_mpm
        df_master[f"Distance_{col}"] = ((df_master["Time_Seconds"] - p_sec) / 60.0) * line_speed_mpm
        probe_start_info[col] = {
            "Start_Sec": p_sec,
            "Start_HHMMSS": df_master[df_master["Time_Seconds"] == p_sec].iloc[0]["Time_HHMMSS"] if p_sec < len(df_master) else "00:00:00",
            "Offset_Sec": p_sec - detected_start_sec, "Offset_Meters": round(offset_m, 2), "Is_First": (col == first_probe_name)
        }

    return {
        "filename": filename, "df_master": df_master, "probe_cols": probe_cols, "invalid_cols": invalid_cols, "furnace_id": furnace_id, "furnace_variant": furnace_variant, "cfg": cfg,
        "line_speed_mpm": line_speed_mpm, "detected_start_sec": detected_start_sec, "detected_start_hhmmss": detected_start_hhmmss, "first_probe_name": first_probe_name,
        "operator_name": operator_name, "company": company, "site": site, "operator_comment": clean_comments_text, "process_settings": process_settings,
        "probe_locations": probe_locations, "probe_start_info": probe_start_info, "embedded_img": embedded_img
    }

# ==============================================================================
# STREAMLIT UI LAYOUT & MAIN APPLICATION
# ==============================================================================
if "paq1_uploader_key" not in st.session_state:
    st.session_state.paq1_uploader_key = 0
if "paq2_uploader_key" not in st.session_state:
    st.session_state.paq2_uploader_key = 0

st.title("🔥 Datapaq .PAQ Furnace Profiler & Analyzer")
st.markdown("Automated thermal profile extraction, zone metrics, and multi-file comparison.")

with st.sidebar:
    st.header("📁 File Upload")
    
    if st.button("🔄 Reset / Clear Data"):
        st.cache_data.clear()
        st.session_state.paq1_uploader_key += 1
        st.session_state.paq2_uploader_key += 1
        st.rerun()
        
    uploaded_file1 = st.file_uploader("Upload Main .PAQ File", type=["paq"], key=f"paq1_{st.session_state.paq1_uploader_key}")

if not uploaded_file1:
    st.info("👈 Please upload a `.paq` binary file using the sidebar to begin analysis.")
else:
    data1 = process_paq_file(uploaded_file1.getvalue(), uploaded_file1.name)
    if not data1:
        st.error("❌ Failed to parse valid probe temperature streams from the uploaded file.")
        st.stop()

    df_m1, f_variant, cfg, zones, probe_cols, invalid_cols = data1["df_master"], data1["furnace_variant"], data1["cfg"], data1["cfg"]["zones"], data1["probe_cols"], data1["invalid_cols"]
    total_furnace_length = zones[-1]["start"] + zones[-1]["length"]
    furnace_duration_mins = total_furnace_length / data1['line_speed_mpm']
    furnace_duration_secs = int(furnace_duration_mins * 60)

    st.success(f"✓ File Loaded Successfully: **{data1['filename']}**")
    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Confirmed Furnace", f_variant)
    m_col2.metric("Conveyor Speed", f"{data1['line_speed_mpm']:.3f} m/min")
    m_col3.metric("Time in Furnace", f"{furnace_duration_secs}s (~{furnace_duration_mins:.1f} min)")

    tabs = st.tabs(["📊 Profile Graphs", "🏭 Zone & Stage Summary", "📈 Statistics & Boxplots", "💾 Data Export & Download", "⚖ Compare Files"])

    with tabs[0]:
        st.subheader("Global Furnace Profile")
        fig1 = go.Figure()
        
        base_date = pd.Timestamp("1970-01-01 00:00:00")
        
        d_max_view = total_furnace_length + 1.0 
        t_max_view = data1['detected_start_sec'] + (d_max_view / data1['line_speed_mpm'] * 60)
        
        t_min = df_m1["Time_Seconds"].min()
        t_max = min(df_m1["Time_Seconds"].max(), t_max_view)
        
        d_min = df_m1["Distance_Meters"].min()
        d_max = min(df_m1["Distance_Meters"].max(), d_max_view)

        custom_hover1 = np.stack((df_m1["Time_HHMMSS"], df_m1["Time_Seconds"], df_m1["Distance_Meters"]), axis=-1)
        for col in probe_cols:
            legend_name = f"<span style='color:gray'>{col}</span>" if col in invalid_cols else col
            fig1.add_trace(go.Scatter(x=df_m1["Time_Stamp"], y=df_m1[col], mode="lines", name=legend_name, customdata=custom_hover1, hovertemplate=f"{col}: %{{y:.1f}} °C<br>Time: %{{customdata[0]}}<br>Dist: %{{customdata[2]:.2f}} m", line=dict(color=PROBE_COLORS.get(col)), xaxis="x"))
            
        for z in zones:
            z_color = GROUP_COLORS.get(z["group"], "rgba(200, 200, 200, 0.2)")
            z_start_sec = (z["start"] / data1['line_speed_mpm']) * 60 + data1['detected_start_sec']
            z_end_sec = ((z["start"] + z["length"]) / data1['line_speed_mpm']) * 60 + data1['detected_start_sec']
            z_start_time = base_date + pd.to_timedelta(z_start_sec, unit="s")
            z_end_time = base_date + pd.to_timedelta(z_end_sec, unit="s")
            fig1.add_vrect(x0=z_start_time, x1=z_end_time, fillcolor=z_color, layer="below", line_width=0.5, line_dash="dot", line_color="rgba(120, 120, 120, 0.4)", annotation_text=f"{z['num']}.{z['name']}", annotation_position="top left", annotation=dict(font_size=9, font_color="#a0aab2", textangle=-90))
            
        fig1.add_hline(y=cfg["trigger_temp_brazing"], line_dash="dash", line_color="red", annotation_text=f"Brazing ({cfg['trigger_temp_brazing']}°C)", annotation_position="bottom right")

        fig1.update_layout(
            title=f"GLOBAL FURNACE PROFILE ({f_variant}): {data1['filename']}", yaxis=dict(title="Temperature (°C)", domain=[0.15, 1.0]), hovermode="x unified", template="plotly_white", height=600, margin=dict(b=80),
            xaxis=dict(title="Time (hh:mm:ss)", tickformat="%H:%M:%S", range=[base_date + pd.to_timedelta(t_min, unit="s"), base_date + pd.to_timedelta(t_max, unit="s")], anchor="y"),
            xaxis2=dict(title="Distance (Meters)", overlaying="x", side="bottom", position=0.0, anchor="free", range=[d_min, d_max])
        )
        fig1.add_trace(go.Scatter(x=df_m1["Distance_Meters"], y=df_m1[probe_cols[0]] * 0, showlegend=False, opacity=0, xaxis="x2", hoverinfo='skip'))
        st.plotly_chart(fig1, use_container_width=True)
        st.markdown("---")
        
        stages = cfg["stages"]
        has_debinder = any(s["Stage"] == "Debinder" for s in stages)
        dryer_info = next((s for s in stages if s["Stage"] == "Dryer"), stages[0])
        debinder_info = next((s for s in stages if s["Stage"] == "Debinder"), None) if has_debinder else None
        brazing_info = next((s for s in stages if s["Stage"] == "Brazing"), stages[-1])

        process_time = df_m1["Time_Seconds"] - data1["detected_start_sec"]
        
        if "NB1" in f_variant:
            dryer_max_df = df_m1[(process_time >= 0) & (process_time <= 300)]
            dryer_dwell_df = dryer_max_df.copy()
            debinder_df = df_m1[(process_time > 300) & (process_time <= 930)] if has_debinder else None
        elif "NB2" in f_variant:
            dryer_max_df = df_m1[(process_time >= 0) & (process_time <= 270)]
            dryer_dwell_df = dryer_max_df.copy()
            debinder_df = None
        elif f_variant == "NB3 (KE8 : M2/EVO)":
            dryer_max_df = df_m1[(process_time >= 0) & (process_time <= 270)]
            dryer_dwell_df = dryer_max_df.copy()
            debinder_df = df_m1[(df_m1["Distance_Meters"] >= debinder_info["Start (m)"]) & (df_m1["Distance_Meters"] <= debinder_info["End (m)"])] if debinder_info else None
        else:
            dryer_max_df = df_m1[(df_m1["Distance_Meters"] >= dryer_info["Start (m)"]) & (df_m1["Distance_Meters"] <= dryer_info["End (m)"])]
            dryer_dwell_df = dryer_max_df.copy()
            debinder_df = df_m1[(df_m1["Distance_Meters"] >= debinder_info["Start (m)"]) & (df_m1["Distance_Meters"] <= debinder_info["End (m)"])] if debinder_info else None
            
        brazing_df = df_m1[(df_m1["Distance_Meters"] >= brazing_info["Start (m)"]) & (df_m1["Distance_Meters"] <= brazing_info["End (m)"])]

        matrix_rows = []
        for col in probe_cols:
            if col in invalid_cols:
                r = {"Probe": col}
                
                r["Brazing Max (°C)"] = "***"
                for bt in [cfg.get(f"brazing_dwell_thresh_{i}") for i in range(1, 5)]:
                    if bt is not None: r[f"Brazing Dwell (≥{int(bt)}°C)"] = "***"
                    
                if has_debinder and debinder_df is not None:
                    d_thresh = cfg.get("debinder_dwell_thresh", 300.0) or 300.0
                    r["Debinder Max (°C)"] = "***"
                    r[f"Debinder Dwell (≥{int(d_thresh)}°C)"] = "***"
                    
                r["Dryer Max (°C)"] = "***"
                for dt in [cfg.get("dryer_dwell_thresh_1"), cfg.get("dryer_dwell_thresh_2")]:
                    if dt is not None: r[f"Dryer Dwell (≥{int(dt)}°C)"] = "***"
                    
                matrix_rows.append(r)
                continue

            r = {"Probe": col}
            
            bz_max = brazing_df[col].max()
            r["Brazing Max (°C)"] = f"{bz_max:.1f}" if not brazing_df.empty and pd.notna(bz_max) else "N/A"
            for bt in [cfg.get(f"brazing_dwell_thresh_{i}") for i in range(1, 5)]:
                if bt is not None: r[f"Brazing Dwell (≥{int(bt)}°C)"] = format_dwell_time((brazing_df[col] >= bt).sum()) if not brazing_df.empty else "00:00:00"

            if has_debinder and debinder_df is not None:
                d_thresh = cfg.get("debinder_dwell_thresh", 300.0) or 300.0
                db_max = debinder_df[col].max()
                r["Debinder Max (°C)"] = f"{db_max:.1f}" if not debinder_df.empty and pd.notna(db_max) else "N/A"
                r[f"Debinder Dwell (≥{int(d_thresh)}°C)"] = format_dwell_time((debinder_df[col] >= d_thresh).sum()) if not debinder_df.empty else "00:00:00"

            d_max = dryer_max_df[col].max()
            r["Dryer Max (°C)"] = f"{d_max:.1f}" if not dryer_max_df.empty and pd.notna(d_max) else "N/A"
            for dt in [cfg.get("dryer_dwell_thresh_1"), cfg.get("dryer_dwell_thresh_2")]:
                if dt is not None: r[f"Dryer Dwell (≥{int(dt)}°C)"] = format_dwell_time((dryer_dwell_df[col] >= dt).sum()) if not dryer_dwell_df.empty else "00:00:00"
                
            matrix_rows.append(r)
            
        if f_variant == "NB1 (RAD)":
            desired_order = ["PB#1", "PB#2", "PB#3", "PB#8", "PB#4", "PB#5", "PB#6", "PB#7"]
            matrix_rows = sorted(matrix_rows, key=lambda x: desired_order.index(x["Probe"]) if x["Probe"] in desired_order else 99)

        st.subheader(f"⏱ Inspection Matrix — {f_variant}")
        
        std_info = STANDARD_SPECS.get(f_variant)
        if std_info:
            st.markdown(f"""
            <div style="background-color: rgba(38, 39, 48, 0.8); padding: 10px; border-left: 5px solid #00ffff; border-radius: 5px; margin-bottom: 15px;">
                <strong style="color: #00ffff; font-size: 1.1rem;">📝 Standard: {std_info['id']}</strong><br>
                <span style="color: #a0aab2; font-size: 0.9rem;"><b>Max Temp:</b> {std_info['max']}<br><b>Dwell Time:</b> {std_info['dwell']}</span>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("""
        <div style="font-size: 0.95rem; margin-bottom: 10px; padding: 10px; border-radius: 5px; background-color: rgba(255,255,255,0.05);">
            <b>Color Legend / คำอธิบายสี:</b>&nbsp;&nbsp;
            <span style="color: #009900; font-weight: bold;">■ Green (สีเขียว)</span>: Pass standard (ผ่านเกณฑ์) &nbsp;&nbsp;|&nbsp;&nbsp;
            <span style="color: #d32f2f; font-weight: bold;">■ Red (สีแดง)</span>: Fail standard (ไม่ผ่านเกณฑ์) &nbsp;&nbsp;|&nbsp;&nbsp;
            <span style="font-weight: bold; opacity: 0.7;">■ Default (สีปกติ)</span>: Reference only (ใช้เพื่ออ้างอิง)
        </div>
        """, unsafe_allow_html=True)

        matrix_placeholder = st.empty()
        check_dryer = st.checkbox("🔍 ตรวจสอบเกณฑ์ Dryer Max Temp & Dwell Time / Evaluate Dryer Max & Dwell", value=False)

        df_matrix = pd.DataFrame(matrix_rows)
        matrix_placeholder.dataframe(
            df_matrix.style.apply(style_inspection_matrix, variant=f_variant, check_dryer_max=check_dryer, axis=1), 
            use_container_width=True, hide_index=True
        )
        
        overall_pass = True
        failed_points = []
        val_rules = VALIDATION_RULES.get(f_variant, {})
        
        for r in matrix_rows:
            probe = r["Probe"]
            if probe in invalid_cols: continue
            for k, v in r.items():
                if k == "Probe": continue
                if not check_dryer and ("Dryer Max" in k or "Dryer Dwell" in k): continue 
                
                rule = val_rules.get(k)
                if f_variant == "NB1 (CDS/KN9/12SHP)" and k == "Brazing Dwell (≥577°C)":
                    if probe in ["PB#1", "PB#5"]: rule = (240, 465)
                    else: rule = (120, 465)
                
                if not rule: continue
                is_fail = False
                if pd.isna(v) or v == "00:00:00" or v == "" or v == 0 or v == "N/A":
                    if rule[0] > 0: is_fail = True
                else:
                    min_v, max_v = rule
                    if "Max (°C)" in k:
                        try:
                            if not (min_v <= float(v) <= max_v): is_fail = True
                        except: pass
                    elif "Dwell" in k:
                        try:
                            parts = str(v).split(':')
                            if len(parts) == 3:
                                total_s = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
                                if not (min_v <= total_s <= max_v): is_fail = True
                        except: pass
                if is_fail:
                    overall_pass = False
                    failed_points.append(f"{probe} ({k})")

        if std_info:
            if overall_pass:
                st.success("✅ **OVERALL STATUS: PASS | สถานะภาพรวม: ผ่านเกณฑ์มาตรฐาน**\n\nThe thermal profile meets all specified requirements for this product. (โปรไฟล์อุณหภูมิผ่านข้อกำหนดทั้งหมดสำหรับผลิตภัณฑ์นี้)")
            else:
                fail_str = ", ".join(list(dict.fromkeys(failed_points)))
                st.error(f"❌ **OVERALL STATUS: FAIL | สถานะภาพรวม: ไม่ผ่านเกณฑ์มาตรฐาน**\n\nThe thermal profile does NOT meet the requirements. Please check the red values in the matrix. (โปรไฟล์อุณหภูมิไม่ผ่านข้อกำหนด กรุณาตรวจสอบค่าสีแดงในตาราง)\n\n**Failed Items (จุดที่ไม่ผ่าน):** {fail_str}")

        st.markdown("---")
        
        st.subheader("👤 Operator Info")
        m1, m2, m3 = st.columns(3)
        m1.text_input("Name", data1["operator_name"], disabled=True)
        m2.text_input("Company", data1["company"], disabled=True)
        m3.text_input("Site", data1["site"], disabled=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_notes, col_recipe = st.columns(2)
        with col_notes:
            st.text_area("💬 Notes for the current file", data1["operator_comment"], height=150)
        with col_recipe:
            st.text_area("⚙ Recipe", data1["process_settings"], height=150)

        st.markdown("---")
        
        col_probes, col_img = st.columns(2)
        with col_probes:
            st.subheader("📍 Probe Locations")
            if data1["probe_locations"]:
                if f_variant == "NB1 (RAD)":
                    desired_order = ["PB#1", "PB#2", "PB#3", "PB#8", "PB#4", "PB#5", "PB#6", "PB#7"]
                    sorted_probes = sorted(data1["probe_locations"].items(), key=lambda x: desired_order.index(x[0]) if x[0] in desired_order else 99)
                else:
                    sorted_probes = sorted(data1["probe_locations"].items(), key=lambda x: int(x[0].replace("PB#", "")) if x[0].replace("PB#", "").isdigit() else 99)
                
                st.dataframe(pd.DataFrame([{"Channel": k, "Attached Location": v} for k, v in sorted_probes]), use_container_width=True, hide_index=True)
            else:
                st.info("No explicit probe location mapping found.")
                
        with col_img:
            if data1["embedded_img"]:
                st.subheader("🖼️ PAQ Image")
                st.image(data1["embedded_img"], use_container_width=True)

        st.markdown("---")
        show_indiv_chart = st.toggle("👁 Show / Hide Individually Aligned Chart", value=False)
        if show_indiv_chart:
            st.subheader("Individually Aligned Probe Chart (Own 60°C Entry)")
            fig2 = go.Figure()
            for col in probe_cols:
                if col in invalid_cols:
                    fig2.add_trace(go.Scatter(x=[np.nan], y=[np.nan], mode="lines", name=f"<span style='color:gray'>{col} (Inactive)</span>", hovertemplate=f"{col} (Inactive)<extra></extra>", line=dict(color=PROBE_COLORS.get(col))))
                    continue
                offset_m = data1["probe_start_info"][col]["Offset_Meters"]
                indiv_hover = np.stack((df_m1["Time_HHMMSS"], df_m1["Time_Seconds"], np.full(len(df_m1), offset_m)), axis=-1)
                disp_name = f"{col} (+{offset_m:.2f}m)" if offset_m > 0 else f"{col} (Lead)"
                fig2.add_trace(go.Scatter(x=df_m1[f"Distance_{col}"], y=df_m1[col], mode="lines", name=disp_name, customdata=indiv_hover, hovertemplate=f"{col}: %{{y:.1f}} °C<br>Indiv Dist: %{{x:.2f}} m<br>Time: %{{customdata[0]}}", line=dict(color=PROBE_COLORS.get(col))))
            for z in zones:
                z_color = GROUP_COLORS.get(z["group"], "rgba(200, 200, 200, 0.2)")
                fig2.add_vrect(x0=z["start"], x1=z["start"] + z["length"], fillcolor=z_color, layer="below", line_width=0.5, line_dash="dot", line_color="rgba(120, 120, 120, 0.4)", annotation_text=f"{z['num']}.{z['name']}", annotation_position="top left", annotation=dict(font_size=9, font_color="#a0aab2", textangle=-90))
            fig2.update_layout(title=f"INDIVIDUALLY ALIGNED PROFILES ({f_variant}): {data1['filename']}", xaxis=dict(title="Individual Probe Distance (Meters from Probe's 60°C Entry)", range=[-1, total_furnace_length + 2]), yaxis_title="Temperature (°C)", hovermode="x unified", template="plotly_white", height=550)
            st.plotly_chart(fig2, use_container_width=True)

    with tabs[1]:
        st.subheader("🔥 Zone Peak Temperatures")
        zone_max_records = []
        for z in zones:
            z_df = df_m1[(df_m1["Distance_Meters"] >= z["start"]) & (df_m1["Distance_Meters"] < round(z["start"] + z["length"], 2))]
            r = {"Group": z["group"], "Zone #": z["num"], "Zone Name": z["name"], "Start (m)": z["start"], "End (m)": round(z["start"] + z["length"], 2)}
            if not z_df.empty and probe_cols:
                max_s = z_df[probe_cols].max()
                for col in probe_cols: 
                    r[col] = "***" if col in invalid_cols else max_s[col]
                
                valid_max = [max_s[c] for c in probe_cols if c not in invalid_cols and pd.notna(max_s[c])]
                r["Zone Peak (°C)"] = max(valid_max) if valid_max else np.nan
                r["Hot Probe"] = max_s[[c for c in probe_cols if c not in invalid_cols]].idxmax() if valid_max else "-"
            else:
                for col in probe_cols: r[col] = "***" if col in invalid_cols else np.nan
                r["Zone Peak (°C)"], r["Hot Probe"] = np.nan, "-"
            zone_max_records.append(r)
        df_zone_summary = pd.DataFrame(zone_max_records)
        valid_cols_for_bg = [c for c in probe_cols if c not in invalid_cols]
        try: st.dataframe(df_zone_summary.style.background_gradient(cmap="OrRd", subset=valid_cols_for_bg + ["Zone Peak (°C)"]).format({col: "{:.2f}" for col in valid_cols_for_bg + ["Zone Peak (°C)"]}), use_container_width=True)
        except: st.dataframe(df_zone_summary, use_container_width=True)

        st.markdown("---")
        st.subheader("⏱️ Entry Alignment (60°C)")
        shift_rows = []
        for col, info in data1["probe_start_info"].items():
            if col in invalid_cols:
                shift_rows.append({"Probe": col, "Start Time (HH:MM:SS)": "***", "Start Sec": "***", "Lag Time vs First": "***", "Distance Shift": "***", "Status": "*** (Inactive)"})
            else:
                shift_rows.append({"Probe": col, "Start Time (HH:MM:SS)": info["Start_HHMMSS"], "Start Sec": f"{info['Start_Sec']}s", "Lag Time vs First": f"+{info['Offset_Sec']}s" if info['Offset_Sec'] > 0 else "0s (Lead)", "Distance Shift": f"+{info['Offset_Meters']:.2f} m" if info['Offset_Meters'] > 0 else "0.00 m (Lead)", "Status": "🏆 First (Lead)" if info["Is_First"] else f"+{info['Offset_Meters']:.2f} m lag"})
        st.dataframe(pd.DataFrame(shift_rows), use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("📈 Temperature Distribution Boxplot by Probe")
        fig_box = go.Figure()
        for idx, col in enumerate(probe_cols): 
            if col not in invalid_cols:
                fig_box.add_trace(go.Box(y=df_m1[col].dropna(), name=col, boxpoints='outliers', marker_color=PROBE_COLORS.get(col)))
        fig_box.update_layout(title="Temperature Distribution Across Probes", yaxis_title="Temperature (°C)", template="plotly_white", height=500)
        st.plotly_chart(fig_box, use_container_width=True)

        st.markdown("---")
        st.subheader("📊 Zone Temperature Statistics (All Probes Combined)")
        stats_list = []
        for z in zones:
            df_z = df_m1[(df_m1["Distance_Meters"] >= z["start"]) & (df_m1["Distance_Meters"] <= z["start"] + z["length"])]
            if not df_z.empty:
                z_vals = df_z[[c for c in probe_cols if c not in invalid_cols]].values.flatten()
                z_vals = z_vals[~np.isnan(z_vals)]
                if len(z_vals) > 0: stats_list.append({"Zone #": z["num"], "Zone Name": z["name"], "Group": z["group"], "Avg Temp (°C)": round(np.mean(z_vals), 2), "Std Dev (°C)": round(np.std(z_vals, ddof=1), 2), "Min Temp (°C)": round(np.min(z_vals), 2), "Max Temp (°C)": round(np.max(z_vals), 2), "Data Points": len(z_vals) })
        st.dataframe(pd.DataFrame(stats_list), use_container_width=True, hide_index=True)

    with tabs[3]:
        st.subheader("💾 Data Export & Download")
        
        row_data = {"File_Name": data1["filename"], "Furnace_Type": f_variant, "Operator_Name": data1["operator_name"], "Company": data1["company"], "Site": data1["site"], "Entrance_Time": data1["detected_start_hhmmss"], "Line_Speed_MPM": data1["line_speed_mpm"]}
        
        max_export_pb = max([int(c.replace("PB#", "")) for c in probe_cols] + [8])
        for pb in [f"PB{i}" for i in range(1, max_export_pb + 1)]:
            ch = f"PB#{pb.replace('PB','')}"
            if ch in probe_cols:
                row_data[f"{pb}_Location"] = data1["probe_locations"].get(ch, "Unlabeled")
                if ch in invalid_cols:
                    row_data[f"{pb}_Start_Time"] = "***"
                    row_data[f"{pb}_Lag_Sec"] = "***"
                else:
                    row_data[f"{pb}_Start_Time"] = data1["probe_start_info"].get(ch, {}).get("Start_HHMMSS", "00:00:00")
                    row_data[f"{pb}_Lag_Sec"] = data1["probe_start_info"].get(ch, {}).get("Offset_Sec", 0)
            else:
                row_data[f"{pb}_Location"] = "No Data"
                row_data[f"{pb}_Start_Time"] = "N/A"
                row_data[f"{pb}_Lag_Sec"] = ""
                
        df_single_row = pd.DataFrame([row_data])

        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 📊 1. Download Analysis Report")
            st.caption("ดาวน์โหลดสรุปผล (Zone Peaks & Inspection Matrix)")
            
            buffer_report = io.BytesIO()
            with pd.ExcelWriter(buffer_report, engine='openpyxl') as writer:
                df_single_row.to_excel(writer, sheet_name="Master_Record", index=False)
                df_zone_summary.to_excel(writer, sheet_name="Zone_Peaks", index=False)
                pd.DataFrame(matrix_rows).to_excel(writer, sheet_name="Inspection_Matrix", index=False)
            
            st.download_button(
                label="📥 Download Report (.xlsx)", 
                data=buffer_report.getvalue(), 
                file_name=f"{os.path.splitext(data1['filename'])[0]}_Report.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
                
        with col2:
            st.markdown("#### 📈 2. Download Raw Data")
            st.caption("ดาวน์โหลดข้อมูลอุณหภูมิดิบที่ใช้แสดงผลกราฟ")
            raw_format = st.radio("เลือกชนิดไฟล์ Raw Data:", ["CSV (.csv)", "Excel (.xlsx)"], horizontal=True, key="radio_raw")
            
            df_raw_export = df_m1.drop(columns=[c for c in df_m1.columns if "Distance_PB#" in c], errors='ignore')
            
            if raw_format == "Excel (.xlsx)":
                buffer_raw = io.BytesIO()
                with pd.ExcelWriter(buffer_raw, engine='openpyxl') as writer:
                    df_raw_export.to_excel(writer, sheet_name="Raw_Profile_Data", index=False)
                
                st.download_button(
                    label="📥 Download Raw Data (.xlsx)", 
                    data=buffer_raw.getvalue(), 
                    file_name=f"{os.path.splitext(data1['filename'])[0]}_RawData.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
            elif raw_format == "CSV (.csv)":
                csv_data = df_raw_export.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Raw Data (.csv)", 
                    data=csv_data, 
                    file_name=f"{os.path.splitext(data1['filename'])[0]}_RawData.csv", 
                    mime="text/csv",
                    use_container_width=True
                )

    with tabs[4]:
        st.subheader("⚖️ Compare Profiles Across Two Files")
        uploaded_file2 = st.file_uploader("📂 Upload 2nd .PAQ File to Compare", type=["paq"], key=f"paq2_{st.session_state.paq2_uploader_key}")
        
        if not uploaded_file2: 
            st.info("👆 Please upload a second `.paq` file above to view the comparison graph.")
        else:
            data2 = process_paq_file(uploaded_file2.getvalue(), uploaded_file2.name)
            if not data2: 
                st.error("❌ Failed to parse second `.paq` file.")
            elif data1["furnace_id"] != data2["furnace_id"]:
                st.error(f"❌ **ข้อมูลเตาอบไม่ตรงกัน (Furnace Mismatch)!**\n\n"
                         f"🇹🇭 ไฟล์หลักคือเตา **{data1['furnace_id']}** แต่ไฟล์ที่เลือกมาเปรียบเทียบคือเตา **{data2['furnace_id']}** กรุณาเลือกไฟล์ที่เป็นเตาอบเดียวกัน\n\n"
                         f"🇬🇧 The main file is **{data1['furnace_id']}**, but the comparison file is **{data2['furnace_id']}**. Please select a file from the same furnace.")
                
                if st.button("รับทราบและเลือกไฟล์ใหม่ (Acknowledge & Select New File)"):
                    st.session_state.paq2_uploader_key += 1
                    st.rerun()
            else:
                df_m2 = data2["df_master"]
                fig_comp = go.Figure()
                
                custom_hover1 = np.stack((df_m1["Time_HHMMSS"], df_m1["Time_Seconds"], df_m1["Distance_Meters"]), axis=-1)
                custom_hover2 = np.stack((df_m2["Time_HHMMSS"], df_m2["Time_Seconds"], df_m2["Distance_Meters"]), axis=-1)

                for z in zones:
                    z_color = GROUP_COLORS.get(z["group"], "rgba(200, 200, 200, 0.2)")
                    fig_comp.add_vrect(
                        x0=z["start"], x1=z["start"] + z["length"], 
                        fillcolor=z_color, layer="below", line_width=0.5, 
                        line_dash="dot", line_color="rgba(120, 120, 120, 0.4)", 
                        annotation_text=f"{z['num']}.{z['name']}", 
                        annotation_position="top left", 
                        annotation=dict(font_size=9, font_color="#a0aab2", textangle=-90)
                    )
                
                fig_comp.add_hline(
                    y=cfg["trigger_temp_brazing"], line_dash="dash", line_color="red", 
                    annotation_text=f"Brazing ({cfg['trigger_temp_brazing']}°C)", 
                    annotation_position="bottom right"
                )
                
                for col in probe_cols:
                    if col in df_m1.columns: 
                        legend_name = f"<span style='color:gray'>F1: {col}</span>" if col in invalid_cols else f"F1: {col}"
                        fig_comp.add_trace(go.Scatter(x=df_m1["Distance_Meters"], y=df_m1[col], mode="lines", name=legend_name, customdata=custom_hover1, hovertemplate=f"F1 {col}: %{{y:.1f}} °C<br>Time: %{{customdata[0]}}<br>Dist: %{{x:.2f}} m", line=dict(color=PROBE_COLORS.get(col), width=1.5)))
                for col in data2["probe_cols"]:
                    if col in df_m2.columns: 
                        legend_name = f"<span style='color:gray'>F2: {col}</span>" if col in data2["invalid_cols"] else f"F2: {col}"
                        fig_comp.add_trace(go.Scatter(x=df_m2["Distance_Meters"], y=df_m2[col], mode="lines", name=legend_name, customdata=custom_hover2, hovertemplate=f"F2 {col}: %{{y:.1f}} °C<br>Time: %{{customdata[0]}}<br>Dist: %{{x:.2f}} m", line=dict(dash='dash', color=PROBE_COLORS.get(col), width=1.5)))
                
                d_max_view = total_furnace_length + 1.0
                d_min_comp = min(df_m1["Distance_Meters"].min(), df_m2["Distance_Meters"].min())
                d_max_actual = max(df_m1["Distance_Meters"].max(), df_m2["Distance_Meters"].max())
                d_max_comp = min(d_max_actual, d_max_view)

                fig_comp.update_layout(
                    title=f"COMPARISON (Aligned by Furnace Entry): {data1['filename']} vs {data2['filename']}", 
                    yaxis=dict(title="Temperature (°C)"), 
                    hovermode="x unified", 
                    template="plotly_white", 
                    height=600,
                    margin=dict(b=80),
                    xaxis=dict(title="Distance (Meters)", range=[d_min_comp, d_max_comp])
                )
                
                st.plotly_chart(fig_comp, use_container_width=True)
