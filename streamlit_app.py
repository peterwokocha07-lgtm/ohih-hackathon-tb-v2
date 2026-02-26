import os
import io
import base64
import random
import hashlib
import datetime as dt
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image

# Optional map libs
MAP_OK = True
try:
    import folium
    from folium.plugins import HeatMap
    from streamlit_folium import st_folium
except Exception:
    MAP_OK = False

# Supabase
SUPA_OK = True
try:
    from supabase import create_client
except Exception:
    SUPA_OK = False


APP_VERSION = "OHIH TB Platform v3 (single-file secure multi-facility)"
st.set_page_config(page_title="OHIH TB Platform", layout="wide")

CSS = """
<style>
.hero{
  background: linear-gradient(135deg, #0ea5e9 0%, #22c55e 55%, #e11d48 100%);
  padding: 16px; border-radius: 18px; color:#fff;
  box-shadow: 0 12px 28px rgba(0,0,0,0.18); margin-bottom: 12px;
}
.hero h1{ margin:0; font-size:28px; }
.hero p{ margin:6px 0 0 0; opacity:0.95; }
.badge{
  display:inline-block; padding:4px 10px; border-radius:999px;
  background: rgba(255,255,255,0.20); border:1px solid rgba(255,255,255,0.25);
  font-size:12px; margin-left:8px;
}
.card{
  background: rgba(255,255,255,0.92);
  border:1px solid rgba(15,23,42,0.10);
  border-radius: 16px; padding: 14px;
  box-shadow: 0 10px 22px rgba(2,6,23,0.06);
}
.ok{ padding:10px;border-radius:12px;background:#ecfdf5;border:1px solid #bbf7d0;}
.warn{ padding:10px;border-radius:12px;background:#fff7ed;border:1px solid #fed7aa;}
.danger{ padding:10px;border-radius:12px;background:#fef2f2;border:1px solid #fecaca;}
.small{ font-size:13px; opacity:0.9; }
.muted{ color: rgba(15,23,42,0.65); }
code{ background: rgba(15,23,42,0.08); padding:2px 6px; border-radius:8px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

ANTI_TB_SVG = """
<svg width="78" height="78" viewBox="0 0 96 96" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="48" cy="48" r="44" stroke="#e11d48" stroke-width="6"/>
  <path d="M48 18 C35 30, 35 45, 48 58 C61 45, 61 30, 48 18Z" fill="#e11d48" opacity="0.9"/>
  <path d="M23 23 L73 73" stroke="#0f172a" stroke-width="8" stroke-linecap="round"/>
</svg>
"""

def hero(title: str, subtitle: str, badge: str = "MVP"):
    st.markdown(
        f"""
        <div class="hero">
          <div style="display:flex;gap:14px;align-items:center;">
            <div>{ANTI_TB_SVG}</div>
            <div style="flex:1;">
              <h1>{title} <span class="badge">{badge}</span></h1>
              <p>{subtitle}</p>
              <div class="small" style="margin-top:6px;">{APP_VERSION}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")

def make_code(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def b64_of_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def safe_get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    # Works locally even if no secrets file exists
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets.get(name))
    except Exception:
        pass
    return os.getenv(name, default)

SUPABASE_URL = safe_get_secret("SUPABASE_URL", "")
SUPABASE_ANON_KEY = safe_get_secret("SUPABASE_ANON_KEY", "") or safe_get_secret("SUPABASE_KEY", "")
APP_PEPPER = safe_get_secret("APP_PEPPER", "CHANGE_ME_PEPPER")
ORGANIZER_MASTER_KEY = safe_get_secret("ORGANIZER_MASTER_KEY", "")

def supabase_ready() -> bool:
    return bool(SUPA_OK and SUPABASE_URL and SUPABASE_ANON_KEY)

def get_supa_client():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def hash_password(pw: str) -> str:
    raw = (APP_PEPPER + pw).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def gen_facility_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(10))

def db_select(table: str, filters: Dict[str, Any] = None, limit: int = 50000, order_col: str = None, desc=True) -> pd.DataFrame:
    supa = get_supa_client()
    q = supa.table(table).select("*").limit(limit)
    if filters:
        for k, v in filters.items():
            q = q.eq(k, v)
    if order_col:
        q = q.order(order_col, desc=desc)
    res = q.execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)
    return pd.DataFrame(res.data or [])

def db_insert(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    supa = get_supa_client()
    res = supa.table(table).insert(row).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)
    return (res.data or [{}])[0]

def db_upsert(table: str, row: Dict[str, Any], on_conflict: Optional[str] = None) -> None:
    supa = get_supa_client()
    res = supa.table(table).upsert(row, on_conflict=on_conflict).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)

# -----------------------------
# DIAGNOSIS "AI" - Explainable Bayesian LR Model
# -----------------------------
TESTS = {
    "GeneXpert": {"sens": 0.88, "spec": 0.98},
    "Smear microscopy": {"sens": 0.60, "spec": 0.98},
    "CXR suggestive": {"sens": 0.75, "spec": 0.70},
}
SYMPTOMS = [
    ("Cough ≥ 2 weeks", 0.08),
    ("Fever", 0.04),
    ("Night sweats", 0.05),
    ("Weight loss", 0.08),
    ("Hemoptysis", 0.10),
    ("Chest pain", 0.03),
    ("Fatigue", 0.03),
]
RISKS = [
    ("Known TB contact", 0.12),
    ("HIV positive", 0.10),
    ("Diabetes", 0.04),
    ("Smoker", 0.03),
    ("Previous TB treatment", 0.10),
    ("Severe malnutrition", 0.07),
]

def lr_pos(sens, spec): return sens / max(1e-9, (1 - spec))
def lr_neg(sens, spec): return (1 - sens) / max(1e-9, spec)

def odds(p):
    p = clamp(p, 1e-9, 1 - 1e-9)
    return p / (1 - p)

def prob_from_odds(o): return o / (1 + o)

def diagnosis_probability(pretest: float, boost: float, evidence: Dict[str, str]) -> Dict[str, Any]:
    p0 = clamp(pretest + boost, 0.01, 0.95)
    o = odds(p0)
    explain = [f"Pre-test probability after symptoms/risks: {p0:.2f}"]

    for test_name, result in evidence.items():
        if test_name not in TESTS or result == "Not done":
            continue
        sens, spec = TESTS[test_name]["sens"], TESTS[test_name]["spec"]
        if result == "Positive":
            LR = lr_pos(sens, spec)
            o *= LR
            explain.append(f"{test_name} Positive → LR+={LR:.2f}")
        elif result == "Negative":
            LR = lr_neg(sens, spec)
            o *= LR
            explain.append(f"{test_name} Negative → LR-={LR:.2f}")

    p = prob_from_odds(o)

    if evidence.get("GeneXpert") == "Positive":
        category = "CONFIRMED TB"
        advice = "Start treatment per guideline, assess HIV, begin contact tracing."
    elif p >= 0.70:
        category = "HIGH probability"
        advice = "Urgent confirmatory testing (GeneXpert). Consider empiric therapy if severe."
    elif p >= 0.35:
        category = "MODERATE probability"
        advice = "Order GeneXpert/microscopy; evaluate differentials; close follow-up."
    elif p >= 0.15:
        category = "LOW–MODERATE probability"
        advice = "Monitor and retest if symptoms persist."
    else:
        category = "LOW probability"
        advice = "TB unlikely. Investigate other causes."

    return {"prob": float(p), "category": category, "advice": advice, "explain": explain}

# -----------------------------
# Microscopy AI prototype
# -----------------------------
def microscopy_score(img_bytes: bytes) -> Dict[str, Any]:
    im = Image.open(io.BytesIO(img_bytes)).convert("L")
    arr = np.array(im).astype(np.float32) / 255.0
    contrast = float(arr.std())
    dark = float((arr < 0.35).mean())
    raw = 0.55 * contrast + 0.45 * dark
    score = clamp((raw - 0.12) / 0.38, 0.0, 1.0)
    pct = score * 100
    if pct >= 70:
        label = "Likely AFB positive (prototype)"
    elif pct >= 40:
        label = "Indeterminate (prototype)"
    else:
        label = "Likely AFB negative (prototype)"
    return {"score_pct": float(pct), "label": label, "contrast": contrast, "dark_density": dark}

# -----------------------------
# Adherence + reminders
# -----------------------------
STREAK_OPTIONS = ["0 days", "1–2 days", "3–6 days", "1 week", "2 weeks", "3 weeks", "1 month or more"]

def missed_over_25pct(missed_28: int) -> bool:
    return int(missed_28) >= 8

def compute_adherence_percent(missed: int, window: int) -> float:
    window = max(1, int(window))
    missed = max(0, int(missed))
    return max(0.0, 100.0 * (1.0 - missed / window))

def risk_model(missed_28: int, streak: str, cumulative_pct: float, completed: bool) -> Dict[str, Any]:
    score = 0.0
    score += min(60.0, missed_28 * 5.0)
    streak_pen = {
        "0 days": 0, "1–2 days": 8, "3–6 days": 18, "1 week": 28,
        "2 weeks": 38, "3 weeks": 48, "1 month or more": 60
    }.get(streak, 10)
    score += streak_pen
    if cumulative_pct < 80: score += 12
    if cumulative_pct < 70: score += 18
    if completed: score -= 8
    score = clamp(score, 0.0, 100.0)

    if score >= 75: cat, msg = "Very High", "High risk of failure/relapse/drug resistance. Urgent follow-up."
    elif score >= 50: cat, msg = "High", "Significant adherence risk. Intensify counseling and monitoring."
    elif score >= 25: cat, msg = "Moderate", "Moderate risk. Reinforce adherence; monitor weekly."
    else: cat, msg = "Low", "Low risk. Continue DOTS monitoring."
    return {"risk_score": float(score), "risk_category": cat, "message": msg}

def make_ics_daily_reminders(summary="Take TB Drugs", hour1=8, hour2=14):
    uid1 = f"{random.randint(100000,999999)}@ohih"
    uid2 = f"{random.randint(100000,999999)}@ohih"
    today = dt.datetime.now()
    dtstart1 = today.replace(hour=hour1, minute=0, second=0, microsecond=0)
    dtstart2 = today.replace(hour=hour2, minute=0, second=0, microsecond=0)
    def fmt(x): return x.strftime("%Y%m%dT%H%M%S")
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//OHIH//TB Reminders//EN
BEGIN:VEVENT
UID:{uid1}
DTSTAMP:{fmt(today)}
DTSTART:{fmt(dtstart1)}
RRULE:FREQ=DAILY
SUMMARY:{summary} (08:00)
END:VEVENT
BEGIN:VEVENT
UID:{uid2}
DTSTAMP:{fmt(today)}
DTSTART:{fmt(dtstart2)}
RRULE:FREQ=DAILY
SUMMARY:{summary} (14:00)
END:VEVENT
END:VCALENDAR
"""
    return ics.encode("utf-8")

# -----------------------------
# Repurposing & docking demo
# -----------------------------
REPURPOSE_DB = [
    {"target":"InhA","drug_name":"Isoniazid (control)","drug_id":"DB00951","notes":"First-line control"},
    {"target":"InhA","drug_name":"Ethionamide","drug_id":"DB00611","notes":"InhA pathway (prodrug)"},
    {"target":"DNA gyrase (GyrA/B)","drug_name":"Levofloxacin","drug_id":"DB01137","notes":"Fluoroquinolone used in TB"},
    {"target":"DNA gyrase (GyrA/B)","drug_name":"Moxifloxacin","drug_id":"DB00218","notes":"Fluoroquinolone used in TB"},
    {"target":"ATP synthase","drug_name":"Bedaquiline","drug_id":"DB08904","notes":"Approved for MDR-TB"},
    {"target":"Ribosome","drug_name":"Linezolid","drug_id":"DB00601","notes":"MDR/XDR regimens"},
    {"target":"RNA polymerase","drug_name":"Rifampicin","drug_id":"DB01045","notes":"First-line TB"},
]
def demo_affinity(name: str) -> float:
    base = (sum(ord(c) for c in name) % 60) / 10.0
    return -6.0 - base

# -----------------------------
# Session state
# -----------------------------
def ss_init():
    st.session_state.setdefault("onboard_step", 1)  # 1..3 (three pages)
    st.session_state.setdefault("facility_id", None)
    st.session_state.setdefault("facility_name", None)
    st.session_state.setdefault("facility_reg", None)
    st.session_state.setdefault("user_role", "standard")
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("profession", None)
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("organizer_mode", False)

    st.session_state.setdefault("pt_step", 1)
    st.session_state.setdefault("pt_draft", {})

ss_init()

# -----------------------------
# DB Setup helper (in-app)
# -----------------------------
SETUP_SQL = """
-- Run this once in Supabase SQL Editor

create table if not exists public.facilities (
  facility_id text primary key,
  facility_name text not null,
  facility_reg text unique not null,
  facility_password_hash text,
  created_at text
);

create table if not exists public.users (
  user_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  full_name text,
  staff_id text,
  profession text,
  role text,
  face_b64 text,
  created_at text,
  unique (facility_id, staff_id)
);

create table if not exists public.patients (
  patient_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  full_name text not null,
  age int,
  sex text,
  weight_kg float,
  height_cm int,
  nationality text,
  religion text,
  phone text,
  email text,
  address text,
  next_of_kin_name text,
  next_of_kin_phone text,
  next_of_kin_email text,
  created_at text
);

create table if not exists public.events (
  event_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  patient_id text references public.patients(patient_id),
  timestamp text,
  state text,
  lga_or_area text,
  lat float,
  lon float,
  tb_probability float,
  category text,
  genexpert text,
  notes text,

  comorbid_dm boolean,
  comorbid_htn boolean,
  comorbid_asthma boolean,
  comorbid_ckd boolean,
  comorbid_cld boolean,
  comorbid_pregnant boolean,

  allergy_drug boolean,
  allergy_food boolean,
  allergy_other text
);

create table if not exists public.dots_daily (
  facility_id text not null references public.facilities(facility_id),
  patient_id text not null references public.patients(patient_id),
  date text not null,
  dose_taken boolean,
  note text,
  created_at text,
  primary key (facility_id, patient_id, date)
);

create table if not exists public.adherence (
  adherence_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  patient_id text not null references public.patients(patient_id),
  timestamp text,
  treatment_start_date text,
  missed_7 int,
  missed_28 int,
  streak text,
  completed boolean,
  adh_7_pct float,
  adh_28_pct float,
  cumulative_pct float,
  flag_over_25pct boolean,
  risk_score float,
  risk_category text,
  notes text
);

create table if not exists public.docking_queue (
  queue_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  timestamp text,
  target text,
  drug_name text,
  drug_id text,
  notes text
);

-- Optional: block deletes (recommended)
revoke delete on public.facilities from anon, authenticated;
revoke delete on public.users from anon, authenticated;
revoke delete on public.patients from anon, authenticated;
revoke delete on public.events from anon, authenticated;
revoke delete on public.dots_daily from anon, authenticated;
revoke delete on public.adherence from anon, authenticated;
revoke delete on public.docking_queue from anon, authenticated;
"""

def db_setup_page():
    st.subheader("Database Setup (if you ever see missing column/table errors)")
    st.caption("Copy this SQL into Supabase → SQL Editor → Run.")
    st.code(SETUP_SQL, language="sql")

# -----------------------------
# Onboarding (3 pages)
# 1) Facility
# 2) User + Face
# 3) Enter Platform
# -----------------------------
def onboarding():
    hero("OHIH TB Platform", "Multi-facility TB diagnosis • adherence • outbreak analytics • repurposing • docking demo", badge="DEPLOYED")

    step = st.session_state["onboard_step"]
    cols = st.columns(3)
    labels = ["1) Facility", "2) User + Face", "3) Enter Platform"]
    for i, c in enumerate(cols, start=1):
        with c:
            st.write(("✅ " if step > i else "➡️ " if step == i else "• ") + labels[i-1])

    if step == 1:
        st.subheader("Facility Sign-in / Register")
        st.caption("Each institution registers once using a facility registration number.")

        colA, colB = st.columns(2)
        with colA:
            facility_name = st.text_input("Institution / Facility name", placeholder="e.g., RSUTH, Braite Whaite Memorial...")
        with colB:
            facility_reg = st.text_input("Facility Registration Number", placeholder="e.g., RSUTH-CH-001")

        mode = st.radio("Choose", ["Register new facility", "Sign in to existing facility"], horizontal=True)
        facility_pw = None
        if mode == "Sign in to existing facility":
            facility_pw = st.text_input("Facility password", type="password")

        if st.button("Continue →", type="primary"):
            if not facility_reg.strip():
                st.error("Enter Facility Registration Number.")
                st.stop()

            try:
                df = db_select("facilities", filters={"facility_reg": facility_reg.strip()}, limit=5)
            except Exception as e:
                st.error(f"Supabase error: {e}")
                db_setup_page()
                st.stop()

            if mode == "Register new facility":
                if not facility_name.strip():
                    st.error("Enter Institution/Facility name.")
                    st.stop()
                if not df.empty:
                    st.error("This registration number already exists. Choose 'Sign in'.")
                    st.stop()

                fid = make_code("FAC")
                pw_plain = gen_facility_password()
                pw_hash = hash_password(pw_plain)

                try:
                    db_insert("facilities", {
                        "facility_id": fid,
                        "facility_name": facility_name.strip(),
                        "facility_reg": facility_reg.strip(),
                        "facility_password_hash": pw_hash,
                        "created_at": now_iso(),
                    })
                except Exception as e:
                    st.error(f"Insert error: {e}")
                    db_setup_page()
                    st.stop()

                st.success("Facility registered ✅")
                st.markdown(
                    f'<div class="warn"><b>IMPORTANT:</b> Save this facility password now (it will not be shown again).<br/><b>Password:</b> <code>{pw_plain}</code></div>',
                    unsafe_allow_html=True
                )

                st.session_state["facility_id"] = fid
                st.session_state["facility_name"] = facility_name.strip()
                st.session_state["facility_reg"] = facility_reg.strip()
                st.session_state["onboard_step"] = 2
                st.rerun()

            else:
                if df.empty:
                    st.error("Facility not found. Use Register or check the number.")
                    st.stop()

                row = df.iloc[0].to_dict()
                if not facility_pw:
                    st.error("Enter facility password.")
                    st.stop()

                if hash_password(facility_pw) != (row.get("facility_password_hash") or ""):
                    st.error("Wrong facility password.")
                    st.stop()

                st.session_state["facility_id"] = row["facility_id"]
                st.session_state["facility_name"] = row["facility_name"]
                st.session_state["facility_reg"] = row["facility_reg"]
                st.session_state["onboard_step"] = 2
                st.rerun()

        st.divider()
        st.subheader("Hackathon Organizer Access (export ALL facilities)")
        master = st.text_input("Organizer master key", type="password", help="Only organizer should know this.")
        if st.button("Unlock organizer mode"):
            if ORGANIZER_MASTER_KEY and master == ORGANIZER_MASTER_KEY:
                st.session_state["organizer_mode"] = True
                st.success("Organizer mode unlocked ✅")
            else:
                st.error("Invalid master key.")

    elif step == 2:
        st.subheader("User + Face ID Enrollment")
        st.info(f"Facility: **{st.session_state['facility_name']}**")

        c1, c2 = st.columns(2)
        with c1:
            user_name = st.text_input("User full name")
            staff_id = st.text_input("User ID / Staff ID")
            profession = st.selectbox("Profession", ["Doctor","Nurse","Lab Scientist","Pharmacist","Data Officer","Community Health Worker","Other"])
            role = st.selectbox("Role", ["standard","admin"], help="Admin can export facility data.")
        with c2:
            face = st.file_uploader("Upload face photo (JPG/PNG)", type=["jpg","jpeg","png"])
            st.caption("MVP FaceID = stored image for identity check (not biometric-grade).")

        back, cont = st.columns(2)
        with back:
            if st.button("← Back"):
                st.session_state["onboard_step"] = 1
                st.rerun()
        with cont:
            if st.button("Continue →", type="primary"):
                if not user_name.strip() or not staff_id.strip():
                    st.error("Enter user name and staff ID.")
                    st.stop()
                if not face:
                    st.error("Upload a face photo.")
                    st.stop()

                face_b64 = b64_of_bytes(face.getbuffer().tobytes())
                uid = make_code("USR")
                try:
                    db_upsert("users", {
                        "user_id": uid,
                        "facility_id": st.session_state["facility_id"],
                        "full_name": user_name.strip(),
                        "staff_id": staff_id.strip(),
                        "profession": profession,
                        "role": role,
                        "face_b64": face_b64,
                        "created_at": now_iso(),
                    }, on_conflict="facility_id,staff_id")
                except Exception as e:
                    st.error(f"User save error: {e}")
                    db_setup_page()
                    st.stop()

                st.session_state["user_name"] = user_name.strip()
                st.session_state["profession"] = profession
                st.session_state["user_role"] = role
                st.session_state["onboard_step"] = 3
                st.rerun()

    else:
        st.subheader("Enter Platform")
        st.markdown(
            f"""
            <div class="card">
              <b>Facility:</b> {st.session_state['facility_name']}<br/>
              <b>User:</b> {st.session_state['user_name']} ({st.session_state['profession']})<br/>
              <b>Role:</b> {st.session_state['user_role']}<br/>
              <span class="small">Central upload: ✅ (Supabase)</span>
            </div>
            """,
            unsafe_allow_html=True
        )
        back, go = st.columns(2)
        with back:
            if st.button("← Back"):
                st.session_state["onboard_step"] = 2
                st.rerun()
        with go:
            if st.button("Login", type="primary"):
                st.session_state["logged_in"] = True
                st.rerun()

# -----------------------------
# Sidebar modules
# -----------------------------
def sidebar():
    with st.sidebar:
        st.markdown("### OHIH TB Platform")
        st.caption("Hackathon deployable MVP")
        st.write(f"**Facility:** {st.session_state['facility_name']}")
        st.write(f"**User:** {st.session_state['user_name']}")
        st.write(f"**Role:** {st.session_state['user_role']}")
        if st.session_state.get("organizer_mode"):
            st.success("Organizer mode: ON")

        st.markdown("---")
        mod = st.radio(
            "Modules",
            [
                "Home",
                "Patients (Registration)",
                "Digital Diagnosis",
                "Microscopy AI",
                "Adherence + DOTS",
                "Drug Repurposing",
                "Docking (Demo) + Interpretation",
                "Outbreak Analytics",
                "Reports + Export",
                "DB Setup Help",
            ],
        )
        st.markdown("---")
        if st.button("Logout"):
            for k in ["logged_in","onboard_step","facility_id","facility_name","facility_reg","user_role","user_name","profession","pt_step","pt_draft","organizer_mode"]:
                if k in st.session_state:
                    del st.session_state[k]
            ss_init()
            st.rerun()
        return mod

# -----------------------------
# Home
# -----------------------------
def home():
    hero("OHIH TB Platform", "Central upload is automatic: every save goes to Supabase.", badge="LIVE")
    st.markdown('<div class="ok"><b>Auto upload:</b> All data is uploaded to the central server (Supabase) immediately when you save.</div>', unsafe_allow_html=True)
    st.markdown('<div class="warn"><b>No delete policy:</b> The app does not show any delete controls. (DB also can block deletes.)</div>', unsafe_allow_html=True)

# -----------------------------
# Patients: step-by-step + summary at every step + no delete
# -----------------------------
def patient_summary_box(d: Dict[str, Any]):
    def val(x): return "" if x is None else str(x)
    st.markdown(
        f"""
        <div class="card">
          <b>Patient summary (confirmation)</b><br/>
          <span class="small">
          <b>Name:</b> {val(d.get("full_name"))}<br/>
          <b>Age/Sex:</b> {val(d.get("age"))} / {val(d.get("sex"))}<br/>
          <b>Wt/Ht:</b> {val(d.get("weight_kg"))} kg / {val(d.get("height_cm"))} cm<br/>
          <b>Nationality:</b> {val(d.get("nationality"))}<br/>
          <b>Religion:</b> {val(d.get("religion"))}<br/>
          <hr/>
          <b>Phone:</b> {val(d.get("phone"))}<br/>
          <b>Email:</b> {val(d.get("email"))}<br/>
          <b>Address:</b> {val(d.get("address"))}<br/>
          <hr/>
          <b>NOK Name:</b> {val(d.get("next_of_kin_name"))}<br/>
          <b>NOK Phone:</b> {val(d.get("next_of_kin_phone"))}<br/>
          <b>NOK Email:</b> {val(d.get("next_of_kin_email"))}<br/>
          </span>
        </div>
        """,
        unsafe_allow_html=True
    )

def patients():
    st.header("Patient Registration (Step-by-step + confirmation summary)")
    fid = st.session_state["facility_id"]

    step = st.session_state["pt_step"]
    draft = st.session_state["pt_draft"]

    ctop = st.columns(3)
    for i, c in enumerate(ctop, start=1):
        with c:
            st.write(("✅ " if step > i else "➡️ " if step == i else "• ") + f"Step {i}")

    left, right = st.columns([1.25, 1])
    with right:
        patient_summary_box(draft)

    with left:
        if step == 1:
            st.subheader("Step 1: Biodata")
            draft["full_name"] = st.text_input("Full name", value=draft.get("full_name",""))
            draft["age"] = st.number_input("Age", 0, 120, int(draft.get("age", 30)))
            draft["sex"] = st.selectbox("Sex", ["Male","Female","Other"], index=["Male","Female","Other"].index(draft.get("sex","Male")))
            draft["weight_kg"] = st.number_input("Weight (kg)", 0.0, 300.0, float(draft.get("weight_kg", 65.0)), step=0.1)
            draft["height_cm"] = st.number_input("Height (cm)", 0, 250, int(draft.get("height_cm", 170)))
            draft["nationality"] = st.text_input("Nationality", value=draft.get("nationality","Nigerian"))
            draft["religion"] = st.text_input("Religion", value=draft.get("religion",""))

            st.markdown('<div class="warn">Check the summary at the right before proceeding.</div>', unsafe_allow_html=True)

            if st.button("Next →", type="primary"):
                if not str(draft.get("full_name","")).strip():
                    st.error("Patient name is required.")
                else:
                    st.session_state["pt_step"] = 2
                    st.session_state["pt_draft"] = draft
                    st.rerun()

        elif step == 2:
            st.subheader("Step 2: Contact details")
            draft["phone"] = st.text_input("Phone number", value=draft.get("phone",""))
            draft["email"] = st.text_input("Email", value=draft.get("email",""))
            draft["address"] = st.text_area("Address", value=draft.get("address",""), height=90)

            st.markdown('<div class="warn">Confirm the summary at the right before proceeding.</div>', unsafe_allow_html=True)

            b1, b2 = st.columns(2)
            with b1:
                if st.button("← Back"):
                    st.session_state["pt_step"] = 1
                    st.session_state["pt_draft"] = draft
                    st.rerun()
            with b2:
                if st.button("Next →", type="primary"):
                    st.session_state["pt_step"] = 3
                    st.session_state["pt_draft"] = draft
                    st.rerun()

        else:
            st.subheader("Step 3: Next of Kin + Final confirmation")
            draft["next_of_kin_name"] = st.text_input("Next of kin name", value=draft.get("next_of_kin_name",""))
            draft["next_of_kin_phone"] = st.text_input("Next of kin phone", value=draft.get("next_of_kin_phone",""))
            draft["next_of_kin_email"] = st.text_input("Next of kin email", value=draft.get("next_of_kin_email",""))

            st.markdown('<div class="danger"><b>NOTE:</b> Once saved, no delete option exists in the app.</div>', unsafe_allow_html=True)
            st.markdown('<div class="warn">Re-check the summary at the right carefully before saving.</div>', unsafe_allow_html=True)

            b1, b2 = st.columns(2)
            with b1:
                if st.button("← Back"):
                    st.session_state["pt_step"] = 2
                    st.session_state["pt_draft"] = draft
                    st.rerun()
            with b2:
                if st.button("✅ Save patient", type="primary"):
                    pid = make_code("PT")
                    try:
                        db_insert("patients", {
                            "patient_id": pid, "facility_id": fid,
                            "full_name": str(draft.get("full_name","")).strip(),
                            "age": int(draft.get("age",0)),
                            "sex": draft.get("sex",""),
                            "weight_kg": float(draft.get("weight_kg",0)),
                            "height_cm": int(draft.get("height_cm",0)),
                            "nationality": str(draft.get("nationality","")).strip(),
                            "religion": str(draft.get("religion","")).strip(),
                            "phone": str(draft.get("phone","")).strip(),
                            "email": str(draft.get("email","")).strip(),
                            "address": str(draft.get("address","")).strip(),
                            "next_of_kin_name": str(draft.get("next_of_kin_name","")).strip(),
                            "next_of_kin_phone": str(draft.get("next_of_kin_phone","")).strip(),
                            "next_of_kin_email": str(draft.get("next_of_kin_email","")).strip(),
                            "created_at": now_iso(),
                        })
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                        st.info("This usually means the DB table is missing the new columns. Open DB Setup Help and run the SQL.")
                        st.stop()

                    st.success(f"Saved ✅ Patient ID: {pid}")
                    st.session_state["pt_step"] = 1
                    st.session_state["pt_draft"] = {}
                    st.rerun()

    st.divider()
    st.subheader("Patient list (facility-only, no delete)")
    try:
        df = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Load patients failed: {e}")
        db_setup_page()

# -----------------------------
# Digital Diagnosis + comorbidities + allergies
# -----------------------------
def diagnosis():
    st.header("Digital Diagnosis (Explainable AI) + Chronic Disease + Allergy")
    fid = st.session_state["facility_id"]

    dfp = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Add patients first.")
        return

    labels = (dfp["patient_id"].astype(str) + " — " + dfp["full_name"].astype(str)).tolist()
    chosen = st.selectbox("Select patient", labels)
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("Symptoms & Risk factors")
    colA, colB = st.columns(2)
    with colA:
        sym_sel = [s for s,_ in SYMPTOMS if st.checkbox(s, False)]
    with colB:
        risk_sel = [r for r,_ in RISKS if st.checkbox(r, False, key=f"r_{r}")]

    boost = sum([w for s,w in SYMPTOMS if s in sym_sel]) + sum([w for r,w in RISKS if r in risk_sel])
    boost = min(boost, 0.35)

    st.subheader("Tests")
    gx = st.selectbox("GeneXpert", ["Not done","Positive","Negative"])
    smear = st.selectbox("Smear microscopy", ["Not done","Positive","Negative"])
    cxr = st.selectbox("CXR suggestive", ["Not done","Positive","Negative"])

    pretest = st.slider("Pre-test probability", 0.01, 0.80, 0.20, 0.01)
    out = diagnosis_probability(pretest, boost, {"GeneXpert": gx, "Smear microscopy": smear, "CXR suggestive": cxr})

    st.markdown(
        f'<div class="ok"><b>TB probability:</b> {100*out["prob"]:.1f}% &nbsp; <b>Category:</b> {out["category"]}<br/>{out["advice"]}</div>',
        unsafe_allow_html=True
    )
    with st.expander("Explainable reasoning"):
        for line in out["explain"]:
            st.write("• " + line)

    st.subheader("Chronic diseases (tick boxes)")
    c1, c2, c3 = st.columns(3)
    with c1:
        dm = st.checkbox("Diabetes Mellitus (DM)")
        htn = st.checkbox("Hypertension (HTN)")
        asthma = st.checkbox("Asthma/COPD")
    with c2:
        ckd = st.checkbox("Chronic Kidney Disease (CKD)")
        cld = st.checkbox("Chronic Liver Disease (CLD)")
        pregnant = st.checkbox("Pregnant")
    with c3:
        allergy_drug = st.checkbox("Drug allergy")
        allergy_food = st.checkbox("Food allergy")
        allergy_other = st.text_input("Other allergy (text)")

    st.subheader("Location for surveillance")
    s1, s2 = st.columns(2)
    with s1:
        state = st.text_input("State", value="Rivers")
        lga = st.text_input("LGA/Area", value="Port Harcourt")
    with s2:
        lat = st.number_input("Latitude (optional)", value=0.0, format="%.4f")
        lon = st.number_input("Longitude (optional)", value=0.0, format="%.4f")

    notes = st.text_area("Clinical notes", height=80)

    if st.button("Save diagnosis event", type="primary"):
        try:
            db_insert("events", {
                "event_id": make_code("EV"),
                "facility_id": fid,
                "patient_id": patient_id,
                "timestamp": now_iso(),
                "state": state.strip(),
                "lga_or_area": lga.strip(),
                "lat": float(lat),
                "lon": float(lon),
                "tb_probability": float(out["prob"]),
                "category": out["category"],
                "genexpert": gx,
                "notes": notes.strip(),
                "comorbid_dm": bool(dm),
                "comorbid_htn": bool(htn),
                "comorbid_asthma": bool(asthma),
                "comorbid_ckd": bool(ckd),
                "comorbid_cld": bool(cld),
                "comorbid_pregnant": bool(pregnant),
                "allergy_drug": bool(allergy_drug),
                "allergy_food": bool(allergy_food),
                "allergy_other": allergy_other.strip(),
            })
            st.success("Saved ✅ (used in Outbreak Analytics)")
        except Exception as e:
            st.error(f"Save failed: {e}")
            st.info("If the DB doesn't have these columns, open DB Setup Help and run SQL.")
            st.stop()

# -----------------------------
# Microscopy AI
# -----------------------------
def microscopy():
    st.header("Microscopy AI (Prototype)")
    img = st.file_uploader("Upload microscopy image (JPG/PNG)", type=["jpg","jpeg","png"])
    if not img:
        st.info("Upload an image to test scoring.")
        return
    b = img.getbuffer().tobytes()
    r = microscopy_score(b)
    st.markdown(
        f'<div class="ok"><b>Suspicion score:</b> {r["score_pct"]:.1f}%<br/>'
        f'<b>Label:</b> {r["label"]}<br/>'
        f'<span class="small">contrast={r["contrast"]:.3f}, dark_density={r["dark_density"]:.3f}</span></div>',
        unsafe_allow_html=True
    )
    st.image(b, use_container_width=True)

# -----------------------------
# Adherence + DOTS + reminders
# -----------------------------
def adherence_dots():
    st.header("Adherence + DOTS + Daily reminders (8am & 2pm)")

    now = dt.datetime.now()
    if now.hour < 8:
        msg = "Reminder: First dose is due at **08:00**."
    elif 8 <= now.hour < 14:
        msg = "Reminder: Second dose is due at **14:00**."
    else:
        msg = "Reminder: Record today's doses (DOTS)."

    st.markdown(f'<div class="warn"><b>Reminder:</b> {msg}<br/><span class="small">Note: Streamlit cannot push notifications if the app is closed. Use the calendar reminders below.</span></div>', unsafe_allow_html=True)

    ics = make_ics_daily_reminders()
    st.download_button("⬇️ Download daily reminders (Calendar .ics)", data=ics, file_name="tb_drug_reminders.ics", mime="text/calendar")

    fid = st.session_state["facility_id"]
    dfp = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Add patients first.")
        return

    labels = (dfp["patient_id"].astype(str) + " — " + dfp["full_name"].astype(str)).tolist()
    chosen = st.selectbox("Select patient", labels)
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("DOTS daily tick (today)")
    today = dt.date.today().isoformat()
    dose_taken = st.checkbox("Dose taken today", True)
    note = st.text_input("Note (optional)", "")

    if st.button("Save DOTS tick", type="primary"):
        try:
            db_upsert("dots_daily", {
                "facility_id": fid,
                "patient_id": patient_id,
                "date": today,
                "dose_taken": bool(dose_taken),
                "note": note.strip(),
                "created_at": now_iso(),
            }, on_conflict="facility_id,patient_id,date")
            st.success("Saved ✅")
        except Exception as e:
            st.error(f"Save failed: {e}")
            st.info("Open DB Setup Help and run SQL if table missing.")
            st.stop()

    dfd = db_select("dots_daily", filters={"facility_id": fid, "patient_id": patient_id}, order_col="date", desc=False)
    if dfd.empty:
        st.info("No DOTS records yet.")
        return

    dfd["date"] = pd.to_datetime(dfd["date"])
    dfd = dfd.sort_values("date")

    def missed_last(n):
        cutoff = pd.Timestamp(dt.date.today() - dt.timedelta(days=n-1))
        w = dfd[dfd["date"] >= cutoff]
        if w.empty:
            return 0
        return int((~w["dose_taken"].astype(bool)).sum())

    missed_7 = missed_last(7)
    missed_28 = missed_last(28)
    adh7 = compute_adherence_percent(missed_7, 7)
    adh28 = compute_adherence_percent(missed_28, 28)

    st.subheader("Adherence summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Missed (7d)", missed_7)
    c2.metric("Adherence (7d)", f"{adh7:.1f}%")
    c3.metric("Missed (28d)", missed_28)
    c4.metric("Adherence (28d)", f"{adh28:.1f}%")

    streak = st.selectbox("Longest missed streak", STREAK_OPTIONS)
    completed = st.checkbox("Completed regimen", False)

    start = dfd["date"].min().date()
    total_days = (dt.date.today() - start).days + 1
    total_expected = max(1, total_days)
    total_taken = int(dfd["dose_taken"].astype(bool).sum())
    cumulative_pct = 100.0 * total_taken / total_expected

    flag = missed_over_25pct(missed_28)
    risk = risk_model(missed_28, streak, cumulative_pct, completed)

    st.markdown(
        f'<div class="{ "danger" if flag else "ok" }">'
        f'<b>Missed-dose threshold:</b> {"⚠️ >25% missed in last 28 days" if flag else "OK"}<br/>'
        f'<b>Risk score:</b> {risk["risk_score"]:.1f}/100 &nbsp; <b>Level:</b> {risk["risk_category"]}<br/>'
        f'{risk["message"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    if st.button("Save adherence snapshot", type="primary"):
        try:
            db_insert("adherence", {
                "adherence_id": make_code("ADH"),
                "facility_id": fid,
                "patient_id": patient_id,
                "timestamp": now_iso(),
                "treatment_start_date": start.isoformat(),
                "missed_7": int(missed_7),
                "missed_28": int(missed_28),
                "streak": streak,
                "completed": bool(completed),
                "adh_7_pct": float(adh7),
                "adh_28_pct": float(adh28),
                "cumulative_pct": float(cumulative_pct),
                "flag_over_25pct": bool(flag),
                "risk_score": float(risk["risk_score"]),
                "risk_category": risk["risk_category"],
                "notes": note.strip(),
            })
            st.success("Saved ✅")
        except Exception as e:
            st.error(f"Save failed: {e}")
            st.info("Open DB Setup Help and run SQL if table missing.")
            st.stop()

    with st.expander("DOTS table"):
        show = dfd.copy()
        show["date"] = show["date"].dt.date.astype(str)
        st.dataframe(show.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

# -----------------------------
# Repurposing
# -----------------------------
def repurposing():
    st.header("Drug Repurposing — shortlist → docking queue")
    fid = st.session_state["facility_id"]
    targets = sorted(list({r["target"] for r in REPURPOSE_DB}))
    target = st.selectbox("Select TB target", targets)
    df = pd.DataFrame([r for r in REPURPOSE_DB if r["target"] == target])
    st.dataframe(df, use_container_width=True, hide_index=True)

    picks = st.multiselect("Select drugs to send to docking queue", df["drug_name"].tolist())
    notes = st.text_input("Notes", "repurposing shortlist")

    if st.button("Send to docking queue", type="primary"):
        if not picks:
            st.error("Select at least 1 drug.")
            return
        for name in picks:
            row = df[df["drug_name"] == name].iloc[0].to_dict()
            db_insert("docking_queue", {
                "queue_id": make_code("DQ"),
                "facility_id": fid,
                "timestamp": now_iso(),
                "target": row["target"],
                "drug_name": row["drug_name"],
                "drug_id": row.get("drug_id",""),
                "notes": notes.strip()
            })
        st.success("Queued ✅ Go to Docking module.")

# -----------------------------
# Docking (demo) + interpretation
# -----------------------------
def docking():
    st.header("Docking (Demo) + Result Interpretation")
    fid = st.session_state["facility_id"]
    dfq = db_select("docking_queue", filters={"facility_id": fid}, order_col="timestamp", desc=True)

    if not dfq.empty:
        st.subheader("Docking Queue")
        st.dataframe(dfq[["timestamp","target","drug_name","drug_id","notes"]], use_container_width=True, hide_index=True)
        default_drug = dfq.iloc[0]["drug_name"]
    else:
        st.info("Queue empty. Add from Repurposing.")
        default_drug = "Demo drug"

    drug = st.text_input("Drug name", value=default_drug)
    if st.button("Run DEMO docking", type="primary"):
        aff = demo_affinity(drug)
        st.success(f"Demo docking complete ✅ Affinity: {aff:.2f} kcal/mol")
        if aff <= -9.0:
            interp = "Strong (screening hit)"
            rec = "Proceed to rescoring, ADMET, and lab validation."
        elif aff <= -7.5:
            interp = "Moderate"
            rec = "Consider optimization and re-docking with controls."
        else:
            interp = "Weak"
            rec = "Lower priority unless supported by other evidence."
        st.markdown(f"**Interpretation:** {interp}\n\n**Next step:** {rec}")

# -----------------------------
# Outbreak analytics
# -----------------------------
def outbreak():
    st.header("Outbreak Detection & Analytics")
    fid = st.session_state["facility_id"]
    dfe = db_select("events", filters={"facility_id": fid}, order_col="timestamp", desc=True)
    if dfe.empty:
        st.info("No events yet. Save diagnosis events.")
        return

    dfe["timestamp"] = pd.to_datetime(dfe["timestamp"], errors="coerce")
    dfe = dfe.dropna(subset=["timestamp"])
    dfe["date"] = dfe["timestamp"].dt.date
    daily = dfe.groupby("date").size().reset_index(name="cases").sort_values("date")
    st.subheader("Daily trend")
    st.line_chart(daily.set_index("date")["cases"])

    st.subheader("Heatmap")
    if not MAP_OK:
        st.error("Heatmap libraries missing. Install: pip install folium streamlit-folium")
        return
    coords = dfe[(dfe.get("lat", 0).abs() > 0) & (dfe.get("lon", 0).abs() > 0)][["lat","lon","tb_probability"]].copy()
    if coords.empty:
        st.info("No valid lat/lon. Enter coordinates in Diagnosis.")
        return
    m = folium.Map(location=[coords["lat"].mean(), coords["lon"].mean()], zoom_start=7)
    heat_data = [[float(r["lat"]), float(r["lon"]), float(r["tb_probability"])] for _, r in coords.iterrows()]
    HeatMap(heat_data, radius=18, blur=14, max_zoom=10).add_to(m)
    st_folium(m, width=1100, height=520)

# -----------------------------
# Reports + export
# -----------------------------
def reports():
    st.header("Reports + Export")
    fid = st.session_state["facility_id"]

    df_pat = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    df_evt = db_select("events", filters={"facility_id": fid}, order_col="timestamp", desc=True)
    df_dot = db_select("dots_daily", filters={"facility_id": fid}, order_col="date", desc=True)
    df_adh = db_select("adherence", filters={"facility_id": fid}, order_col="timestamp", desc=True)
    df_q = db_select("docking_queue", filters={"facility_id": fid}, order_col="timestamp", desc=True)

    st.subheader("Facility downloads")
    c1,c2,c3,c4,c5 = st.columns(5)
    def dl(df, name, col):
        with col:
            st.download_button(f"{name}.csv", df.to_csv(index=False).encode("utf-8"), f"{name}.csv", "text/csv", use_container_width=True)
    dl(df_pat,"patients",c1); dl(df_evt,"events",c2); dl(df_dot,"dots_daily",c3); dl(df_adh,"adherence",c4); dl(df_q,"docking_queue",c5)

    st.divider()
    st.subheader("Export ALL facilities (Organizer only)")
    if not st.session_state.get("organizer_mode"):
        st.info("Organizer mode is locked. Unlock it at Facility page using ORGANIZER_MASTER_KEY.")
        return

    if st.button("Generate ALL facilities export", type="primary"):
        all_fac = db_select("facilities", limit=50000)
        all_pat = db_select("patients", limit=50000)
        all_evt = db_select("events", limit=50000)
        all_dot = db_select("dots_daily", limit=50000)
        all_adh = db_select("adherence", limit=50000)
        all_q = db_select("docking_queue", limit=50000)

        st.success("Loaded ✅")
        st.download_button("ALL_facilities.csv", all_fac.to_csv(index=False).encode("utf-8"), "ALL_facilities.csv", "text/csv")
        st.download_button("ALL_patients.csv", all_pat.to_csv(index=False).encode("utf-8"), "ALL_patients.csv", "text/csv")
        st.download_button("ALL_events.csv", all_evt.to_csv(index=False).encode("utf-8"), "ALL_events.csv", "text/csv")
        st.download_button("ALL_dots_daily.csv", all_dot.to_csv(index=False).encode("utf-8"), "ALL_dots_daily.csv", "text/csv")
        st.download_button("ALL_adherence.csv", all_adh.to_csv(index=False).encode("utf-8"), "ALL_adherence.csv", "text/csv")
        st.download_button("ALL_docking_queue.csv", all_q.to_csv(index=False).encode("utf-8"), "ALL_docking_queue.csv", "text/csv")

# -----------------------------
# MAIN
# -----------------------------
if not supabase_ready():
    st.error("Missing Supabase credentials. Add SUPABASE_URL and SUPABASE_ANON_KEY in Streamlit Secrets (Cloud) or .streamlit/secrets.toml (local).")
    st.stop()

if not st.session_state["logged_in"]:
    onboarding()
else:
    mod = sidebar()
    if mod == "Home":
        home()
    elif mod == "Patients (Registration)":
        patients()
    elif mod == "Digital Diagnosis":
        diagnosis()
    elif mod == "Microscopy AI":
        microscopy()
    elif mod == "Adherence + DOTS":
        adherence_dots()
    elif mod == "Drug Repurposing":
        repurposing()
    elif mod == "Docking (Demo) + Interpretation":
        docking()
    elif mod == "Outbreak Analytics":
        outbreak()
    elif mod == "Reports + Export":
        reports()
    elif mod == "DB Setup Help":
        db_setup_page()