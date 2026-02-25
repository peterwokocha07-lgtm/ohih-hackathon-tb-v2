# streamlit_app.py
# OHIH TB Platform (Multi-facility) - Single-file MVP
# - 4-page onboarding (facility -> user -> face enroll -> login)
# - Supabase backend (multi-facility + centralized data)
# - Patient demographics (name/age/sex/weight/height/nationality/religion)
# - Obj1 Repurposing, Obj2 Diagnosis (Bayesian/LR), Obj3 Docking (demo + local Vina note),
#   Obj4 Outbreak Analytics (heatmap), Obj5 Dashboard, DOTS adherence + >25% flag, Reports, Demo data generator.

import os
import io
import math
import json
import time
import base64
import random
import datetime as dt
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np
import streamlit as st

# Optional mapping libs (heatmap)
MAP_OK = True
try:
    import folium
    from folium.plugins import HeatMap
    from streamlit_folium import st_folium
except Exception:
    MAP_OK = False

# Supabase client
SUPA_OK = True
try:
    from supabase import create_client
except Exception:
    SUPA_OK = False


# -----------------------------
# CONFIG / BRANDING
# -----------------------------
st.set_page_config(page_title="OHIH TB Platform", layout="wide")

ANTI_TB_SVG = """
<svg width="86" height="86" viewBox="0 0 96 96" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="48" cy="48" r="44" stroke="#e11d48" stroke-width="6"/>
  <path d="M48 18 C35 30, 35 45, 48 58 C61 45, 61 30, 48 18Z" fill="#e11d48" opacity="0.9"/>
  <path d="M35 56 C28 60, 26 70, 34 76 C40 80, 47 78, 52 74 C45 72, 39 66, 35 56Z" fill="#e11d48" opacity="0.7"/>
  <path d="M61 56 C68 60, 70 70, 62 76 C56 80, 49 78, 44 74 C51 72, 57 66, 61 56Z" fill="#e11d48" opacity="0.7"/>
  <path d="M23 23 L73 73" stroke="#0f172a" stroke-width="8" stroke-linecap="round"/>
</svg>
"""

CSS = """
<style>
  .ohih-hero {
    background: linear-gradient(135deg, #0ea5e9 0%, #22c55e 45%, #e11d48 100%);
    padding: 18px 18px;
    border-radius: 18px;
    color: white;
    box-shadow: 0 12px 30px rgba(0,0,0,0.15);
    margin-bottom: 12px;
  }
  .ohih-hero h1 { margin: 0; font-size: 28px; }
  .ohih-hero p { margin: 6px 0 0 0; opacity: 0.95; }
  .ohih-card {
    background: rgba(255,255,255,0.8);
    border: 1px solid rgba(15,23,42,0.08);
    border-radius: 16px;
    padding: 14px 14px;
    box-shadow: 0 10px 22px rgba(2,6,23,0.06);
  }
  .ohih-badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(255,255,255,0.18);
    border: 1px solid rgba(255,255,255,0.25);
    margin-left: 8px;
    font-size: 12px;
  }
  .ohih-small { font-size: 13px; opacity: 0.9; }
  .ohih-warn { padding:10px;border-radius:12px;background:#fff7ed;border:1px solid #fed7aa; }
  .ohih-ok { padding:10px;border-radius:12px;background:#ecfdf5;border:1px solid #bbf7d0; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# -----------------------------
# SUPABASE UTIL
# -----------------------------
def get_supa():
    """Create Supabase client from Streamlit secrets or environment variables."""
    if not SUPA_OK:
        st.error("Supabase client not installed. Add `supabase` to requirements.txt.")
        st.stop()

    url = None
    key = None
    # Streamlit Cloud uses st.secrets
    if hasattr(st, "secrets"):
        url = st.secrets.get("SUPABASE_URL", None)
        key = st.secrets.get("SUPABASE_ANON_KEY", None) or st.secrets.get("SUPABASE_KEY", None)

    # fallback: env vars
    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")

    if not url or not key:
        st.error("Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_ANON_KEY in Streamlit Secrets.")
        st.stop()

    return create_client(url, key)


def supa_insert(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    supa = get_supa()
    res = supa.table(table).insert(row).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)
    return res.data[0] if res.data else {}


def supa_upsert(table: str, row: Dict[str, Any], on_conflict: Optional[str] = None) -> None:
    supa = get_supa()
    res = supa.table(table).upsert(row, on_conflict=on_conflict).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)


def supa_select(table: str, filters: Dict[str, Any] = None, limit: int = 1000, order_col: Optional[str] = None, desc: bool = True) -> pd.DataFrame:
    supa = get_supa()
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


def supa_delete_where(table: str, col: str, val: Any) -> None:
    supa = get_supa()
    res = supa.table(table).delete().eq(col, val).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)


# -----------------------------
# ID HELPERS
# -----------------------------
def make_code(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"


def b64_of_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# -----------------------------
# CLINICAL AI (Obj2) - Bayesian/LR
# -----------------------------
def lr_pos(sens: float, spec: float) -> float:
    denom = max(1e-9, (1.0 - spec))
    return sens / denom


def lr_neg(sens: float, spec: float) -> float:
    denom = max(1e-9, spec)
    return (1.0 - sens) / denom


def odds(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return p / (1 - p)


def prob_from_odds(o: float) -> float:
    return o / (1 + o)


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


def diagnosis_probability(pretest: float, symptom_boost: float, test_evidence: Dict[str, str]) -> Dict[str, Any]:
    """
    Explainable clinical AI:
    - start with pretest p
    - add symptom/risk boost (capped)
    - apply LRs for tests.
    """
    p0 = min(max(pretest + symptom_boost, 0.01), 0.95)
    o = odds(p0)

    explain = []
    explain.append(f"Pre-test probability: {p0:.2f} (after symptoms/risks)")

    for tname, result in test_evidence.items():
        if tname not in TESTS or result == "Not done":
            continue
        sens, spec = TESTS[tname]["sens"], TESTS[tname]["spec"]
        if result == "Positive":
            LR = lr_pos(sens, spec)
            o *= LR
            explain.append(f"{tname} Positive: LR+={LR:.2f}")
        elif result == "Negative":
            LR = lr_neg(sens, spec)
            o *= LR
            explain.append(f"{tname} Negative: LR-={LR:.2f}")

    p = prob_from_odds(o)

    if test_evidence.get("GeneXpert") == "Positive":
        category = "CONFIRMED TB"
        advice = "Start TB treatment per national guidelines; assess HIV status; initiate contact tracing."
    elif p >= 0.70:
        category = "HIGH probability"
        advice = "Urgent confirmatory testing (GeneXpert if not done); consider starting treatment if clinically indicated."
    elif p >= 0.35:
        category = "MODERATE probability"
        advice = "Do GeneXpert / microscopy; evaluate alternative diagnoses; follow up closely."
    elif p >= 0.15:
        category = "LOW–MODERATE probability"
        advice = "Monitor; investigate other causes; repeat testing if symptoms persist."
    else:
        category = "LOW probability"
        advice = "TB unlikely; treat other likely causes; return if worsening."

    return {"prob": float(p), "category": category, "advice": advice, "explain": explain}


# -----------------------------
# Microscopy AI (A) - prototype scoring
# -----------------------------
def microscopy_score(img_bytes: bytes) -> Dict[str, Any]:
    # Lightweight heuristic: contrast + dark density
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("L")
    arr = np.array(im).astype(np.float32) / 255.0
    contrast = float(arr.std())
    dark = float((arr < 0.35).mean())

    raw = 0.55 * contrast + 0.45 * dark
    score = max(0.0, min(1.0, (raw - 0.12) / 0.38))  # normalize
    pct = score * 100.0

    if pct >= 70:
        label = "Likely AFB positive (prototype)"
    elif pct >= 40:
        label = "Indeterminate (prototype)"
    else:
        label = "Likely AFB negative (prototype)"

    return {"score_pct": float(pct), "label": label, "contrast": contrast, "dark_density": dark}


# -----------------------------
# Adherence + DOTS (B)
# -----------------------------
STREAK_OPTIONS = ["0 days", "1–2 days", "3–6 days", "1 week", "2 weeks", "3 weeks", "1 month or more"]


def missed_over_25pct(missed_28: int) -> bool:
    # 28 doses expected in 28 days for daily regimen; >25% = >7
    return int(missed_28) >= 8


def compute_adherence_percent(missed: int, window: int) -> float:
    window = max(1, int(window))
    missed = max(0, int(missed))
    return max(0.0, 100.0 * (1.0 - missed / window))


def risk_model(missed_28: int, streak: str, cumulative_pct: float, completed: bool) -> Dict[str, Any]:
    # simple explainable risk score
    score = 0.0
    score += min(60.0, missed_28 * 5.0)  # 0..60
    streak_pen = {
        "0 days": 0, "1–2 days": 8, "3–6 days": 18, "1 week": 28,
        "2 weeks": 38, "3 weeks": 48, "1 month or more": 60
    }.get(streak, 10)
    score += streak_pen
    if cumulative_pct < 80:
        score += 12
    if cumulative_pct < 70:
        score += 18
    if completed:
        score -= 8

    score = max(0.0, min(100.0, score))

    if score >= 75:
        cat = "Very High"
        msg = "High risk of treatment failure / relapse / drug resistance. Urgent follow-up required."
    elif score >= 50:
        cat = "High"
        msg = "Significant adherence risk. Intensify counseling and follow-up."
    elif score >= 25:
        cat = "Moderate"
        msg = "Moderate risk. Reinforce adherence, monitor weekly."
    else:
        cat = "Low"
        msg = "Low risk. Continue DOTS routine monitoring."

    return {"risk_score": float(score), "risk_category": cat, "message": msg}


# -----------------------------
# Obj1 Repurposing + Queue
# -----------------------------
REPURPOSE_DB = [
    {"target": "InhA", "drug_name": "Isoniazid (control)", "drug_id": "DB00951", "notes": "First-line TB control"},
    {"target": "InhA", "drug_name": "Ethionamide", "drug_id": "DB00611", "notes": "InhA pathway (prodrug)"},
    {"target": "DNA gyrase (GyrA/B)", "drug_name": "Levofloxacin", "drug_id": "DB01137", "notes": "Fluoroquinolone used in TB"},
    {"target": "DNA gyrase (GyrA/B)", "drug_name": "Moxifloxacin", "drug_id": "DB00218", "notes": "Fluoroquinolone used in TB"},
    {"target": "ATP synthase", "drug_name": "Bedaquiline", "drug_id": "DB08904", "notes": "Approved for MDR-TB"},
    {"target": "Ribosome", "drug_name": "Linezolid", "drug_id": "DB00601", "notes": "MDR/XDR regimens"},
    {"target": "RNA polymerase", "drug_name": "Rifampicin", "drug_id": "DB01045", "notes": "First-line TB"},
    {"target": "Cell wall (DprE1 context)", "drug_name": "Pretomanid (context)", "drug_id": "DB09241", "notes": "BPaL/BPaLM regimens"},
]


# -----------------------------
# DEMO DATA GENERATOR
# -----------------------------
AREAS = [
    {"state": "Rivers", "lga": "Port Harcourt", "lat": 4.8156, "lon": 7.0498},
    {"state": "Rivers", "lga": "Obio/Akpor", "lat": 4.8400, "lon": 6.9700},
    {"state": "Rivers", "lga": "Eleme", "lat": 4.7900, "lon": 7.1200},
    {"state": "Lagos", "lga": "Ikeja", "lat": 6.6018, "lon": 3.3515},
    {"state": "Abuja (FCT)", "lga": "Garki", "lat": 9.0333, "lon": 7.5333},
    {"state": "Kano", "lga": "Municipal", "lat": 12.0000, "lon": 8.5167},
]


def jitter(lat, lon, spread=0.12):
    return lat + random.uniform(-spread, spread), lon + random.uniform(-spread, spread)


def generate_demo_data(facility_id: str, n_events=80, days=30, spike="Rivers|Port Harcourt", spike_strength=3):
    spike_state, spike_lga = [x.strip() for x in spike.split("|")]
    spike_area = [a for a in AREAS if a["state"] == spike_state and a["lga"] == spike_lga]
    spike_area = spike_area[0] if spike_area else AREAS[0]

    # create some demo patients
    demo_patients = []
    for i in range(8):
        pid = make_code("PT")
        demo_patients.append(pid)
        supa_insert("patients", {
            "patient_id": pid,
            "facility_id": facility_id,
            "full_name": f"Demo Patient {i+1}",
            "age": random.randint(18, 65),
            "sex": random.choice(["Male", "Female"]),
            "weight_kg": round(random.uniform(45, 92), 1),
            "height_cm": random.randint(150, 190),
            "nationality": "Nigerian",
            "religion": random.choice(["Christianity", "Islam", "Other"]),
            "created_at": now_iso(),
        })

    now = dt.datetime.now()
    for _ in range(int(n_events)):
        day_offset = int(random.triangular(0, days - 1, 3))
        ts = now - dt.timedelta(days=day_offset, hours=random.randint(0, 23), minutes=random.randint(0, 59))

        choose_spike = (day_offset <= 7) and (random.random() < min(0.85, 0.25 * spike_strength))
        area = spike_area if choose_spike else random.choice(AREAS)
        lat, lon = jitter(area["lat"], area["lon"], 0.12)

        base_prob = random.betavariate(2, 5)
        if choose_spike:
            base_prob = min(1.0, base_prob + random.uniform(0.25, 0.55))

        gx = random.choices(["Not done", "Positive", "Negative"], weights=[0.5, 0.25, 0.25])[0]
        if gx == "Positive":
            base_prob = max(base_prob, random.uniform(0.70, 0.95))

        patient_id = random.choice(demo_patients)

        supa_insert("events", {
            "event_id": make_code("EV"),
            "facility_id": facility_id,
            "patient_id": patient_id,
            "timestamp": ts.isoformat(timespec="seconds"),
            "state": area["state"],
            "lga_or_area": area["lga"],
            "lat": float(lat),
            "lon": float(lon),
            "tb_probability": float(base_prob),
            "category": "DEMO",
            "genexpert": gx,
            "notes": "demo event",
        })

    # DOTS demo
    patients = demo_patients[:5]
    for p in patients:
        start_date = dt.date.today() - dt.timedelta(days=random.randint(10, 120))
        for d in range(0, 60):
            date = dt.date.today() - dt.timedelta(days=d)
            if date < start_date:
                continue
            taken_prob = 0.65 if random.random() < 0.35 else 0.88
            dose_taken = random.random() < taken_prob
            supa_upsert("dots_daily", {
                "facility_id": facility_id,
                "patient_id": p,
                "date": date.isoformat(),
                "dose_taken": bool(dose_taken),
                "note": "demo tick",
                "created_at": now_iso(),
            }, on_conflict="facility_id,patient_id,date")

    # Docking queue demo
    for row in [
        {"target": "InhA", "drug_name": "Isoniazid (control)", "drug_id": "DB00951"},
        {"target": "DNA gyrase (GyrA/B)", "drug_name": "Moxifloxacin", "drug_id": "DB00218"},
        {"target": "ATP synthase", "drug_name": "Bedaquiline", "drug_id": "DB08904"},
    ]:
        supa_insert("docking_queue", {
            "queue_id": make_code("DQ"),
            "facility_id": facility_id,
            "timestamp": now_iso(),
            "target": row["target"],
            "drug_name": row["drug_name"],
            "drug_id": row["drug_id"],
            "notes": "demo queue",
        })


# -----------------------------
# SESSION STATE
# -----------------------------
def ss_init():
    st.session_state.setdefault("auth_step", 1)  # 1..4
    st.session_state.setdefault("facility_id", None)
    st.session_state.setdefault("facility_name", None)
    st.session_state.setdefault("user_id", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("user_role", "standard")  # admin/standard
    st.session_state.setdefault("profession", None)
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("face_enrolled", False)
    st.session_state.setdefault("face_b64", None)


ss_init()


# -----------------------------
# ONBOARDING / LOGIN WIZARD (4 pages)
# -----------------------------
def hero(title: str, subtitle: str, badge: str = ""):
    st.markdown(
        f"""
        <div class="ohih-hero">
          <div style="display:flex;gap:14px;align-items:center;">
            <div>{ANTI_TB_SVG}</div>
            <div style="flex:1;">
              <h1>{title} {f'<span class="ohih-badge">{badge}</span>' if badge else ''}</h1>
              <p>{subtitle}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def require_login():
    if not st.session_state.get("logged_in"):
        st.stop()


def onboarding_ui():
    hero(
        "OHIH TB Platform",
        "Multi-facility TB diagnosis • adherence • outbreak analytics • repurposing • docking demo",
        badge="MVP",
    )

    step = st.session_state["auth_step"]

    cols = st.columns(4)
    labels = ["1) Facility", "2) User", "3) Face ID", "4) Enter Platform"]
    for i, c in enumerate(cols, start=1):
        with c:
            st.write(("✅ " if step > i else "➡️ " if step == i else "• ") + labels[i - 1])

    st.write("")

    # PAGE 1: Facility
    if step == 1:
        st.subheader("Facility Sign-in / Register")
        st.caption("For multi-facility use, each institution registers once using a facility registration number.")

        colA, colB = st.columns(2)
        with colA:
            facility_name = st.text_input("Institution / Facility name", placeholder="e.g., RSUTH, Braite Whaite Memorial, International Secondary School Clinic")
        with colB:
            facility_reg = st.text_input("Facility Registration Number", placeholder="e.g., RSUTH-CH-001")

        mode = st.radio("Choose", ["Register new facility", "Sign in to existing facility"], horizontal=True)

        if st.button("Continue →", type="primary"):
            if not facility_name or not facility_reg:
                st.error("Enter BOTH facility name and registration number.")
                st.stop()

            # Try locate facility by reg number
            df = supa_select("facilities", filters={"facility_reg": facility_reg}, limit=5)
            if mode == "Register new facility":
                if not df.empty:
                    st.error("This facility registration number already exists. Choose 'Sign in'.")
                    st.stop()
                fid = make_code("FAC")
                supa_insert("facilities", {
                    "facility_id": fid,
                    "facility_name": facility_name.strip(),
                    "facility_reg": facility_reg.strip(),
                    "created_at": now_iso(),
                })
                st.success("Facility registered ✅")
            else:
                if df.empty:
                    st.error("Facility not found. Use 'Register new facility' or check the registration number.")
                    st.stop()
                fid = df.iloc[0]["facility_id"]
                facility_name = df.iloc[0]["facility_name"]

            st.session_state["facility_id"] = fid
            st.session_state["facility_name"] = facility_name
            st.session_state["auth_step"] = 2
            st.rerun()

    # PAGE 2: User
    elif step == 2:
        st.subheader("User Profile (Staff)")
        st.caption("Each staff member registers under the facility. Admin users can export all facility data.")

        st.info(f"Facility: **{st.session_state['facility_name']}**")

        colA, colB = st.columns(2)
        with colA:
            user_name = st.text_input("Full name", placeholder="e.g., Dr Wokocha Peter Gift")
            staff_id = st.text_input("Staff ID / User ID number", placeholder="e.g., RSU-CP-014")
        with colB:
            profession = st.selectbox("Profession", ["Doctor", "Nurse", "Lab Scientist", "Pharmacist", "Data Officer", "Community Health Worker", "Other"])
            role = st.selectbox("Role", ["standard", "admin"], help="Admin can export facility-wide datasets.")

        consent = st.checkbox("I confirm I have permission to register this user and I consent to basic audit logging.", value=True)

        colC, colD = st.columns(2)
        with colC:
            if st.button("← Back"):
                st.session_state["auth_step"] = 1
                st.rerun()
        with colD:
            if st.button("Continue →", type="primary"):
                if not consent:
                    st.error("Consent required.")
                    st.stop()
                if not user_name or not staff_id:
                    st.error("Enter full name and staff ID.")
                    st.stop()

                fid = st.session_state["facility_id"]
                # Upsert user by unique (facility_id, staff_id)
                uid = make_code("USR")
                supa_upsert("users", {
                    "user_id": uid,
                    "facility_id": fid,
                    "full_name": user_name.strip(),
                    "staff_id": staff_id.strip(),
                    "profession": profession,
                    "role": role,
                    "created_at": now_iso(),
                }, on_conflict="facility_id,staff_id")

                # Retrieve actual user row
                dfu = supa_select("users", filters={"facility_id": fid, "staff_id": staff_id.strip()}, limit=5)
                row = dfu.iloc[0].to_dict()

                st.session_state["user_id"] = row["user_id"]
                st.session_state["user_name"] = row["full_name"]
                st.session_state["profession"] = row.get("profession", profession)
                st.session_state["user_role"] = row.get("role", role)
                st.session_state["auth_step"] = 3
                st.rerun()

    # PAGE 3: Face ID enroll (MVP - enroll only, not verification)
    elif step == 3:
        st.subheader("Face ID Enrollment (MVP)")
        st.caption("MVP uses face enrollment (photo capture/upload) for recognition/audit. Verification matching can be added later.")

        consent = st.checkbox("I consent to capture/store my facial image for login audit (demo use).", value=True)
        face = st.file_uploader("Upload a clear face photo (JPG/PNG)", type=["jpg", "jpeg", "png"])

        st.markdown('<div class="ohih-warn"><b>Note:</b> This is enrollment only in the hackathon MVP. For production, we add real face matching + encryption + strict access control.</div>', unsafe_allow_html=True)

        colA, colB = st.columns(2)
        with colA:
            if st.button("← Back"):
                st.session_state["auth_step"] = 2
                st.rerun()
        with colB:
            if st.button("Enroll & Continue →", type="primary"):
                if not consent:
                    st.error("Consent required to proceed.")
                    st.stop()
                if not face:
                    st.error("Upload a face photo.")
                    st.stop()

                fid = st.session_state["facility_id"]
                uid = st.session_state["user_id"]
                b = face.getbuffer().tobytes()
                b64 = b64_of_bytes(b)

                # store enrollment into users table
                supa_upsert("users", {
                    "user_id": uid,
                    "facility_id": fid,
                    "face_b64": b64,
                    "face_enrolled_at": now_iso(),
                }, on_conflict="user_id")

                st.session_state["face_enrolled"] = True
                st.session_state["face_b64"] = b64
                st.session_state["auth_step"] = 4
                st.rerun()

    # PAGE 4: Enter platform
    elif step == 4:
        st.subheader("Enter Platform")
        st.markdown(
            f"""
            <div class="ohih-card">
              <b>Facility:</b> {st.session_state['facility_name']}<br/>
              <b>User:</b> {st.session_state['user_name']} ({st.session_state['profession']})<br/>
              <b>Role:</b> {st.session_state['user_role']}<br/>
              <span class="ohih-small">Face enrolled: {'✅' if st.session_state.get('face_enrolled') else '❌'}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        colA, colB = st.columns(2)
        with colA:
            if st.button("← Back"):
                st.session_state["auth_step"] = 3
                st.rerun()
        with colB:
            if st.button("Login to OHIH TB Platform", type="primary"):
                st.session_state["logged_in"] = True
                st.rerun()


# -----------------------------
# MAIN APP MODULES
# -----------------------------
def sidebar_header():
    with st.sidebar:
        st.markdown("### OHIH TB Platform")
        st.caption("Multi-facility • Central DB • Hackathon MVP")
        st.markdown("---")
        if st.session_state.get("logged_in"):
            st.write(f"**Facility:** {st.session_state['facility_name']}")
            st.write(f"**User:** {st.session_state['user_name']}")
            st.write(f"**Role:** {st.session_state['user_role']}")
            st.markdown("---")


def module_home():
    hero("OHIH TB Platform", "End-to-end TB control: diagnosis → outbreak analytics → adherence → repurposing → docking demo", badge="LIVE")

    st.markdown("### Quick start for testers")
    st.markdown(
        """
1) Click **Generate demo data** (creates patients, events, DOTS, docking queue)  
2) Go to **Outbreak Analytics** and confirm trend + heatmap  
3) Go to **Digital Diagnosis**, run a case and **Save event**  
4) Go to **Adherence + DOTS**, tick dose and see **>25% risk flag**  
5) Go to **Reports**, download CSV exports  
        """
    )

    st.divider()
    st.subheader("Hackathon Demo Data Generator")

    fid = st.session_state["facility_id"]

    colA, colB = st.columns([1, 1])
    with colA:
        n_events = st.slider("Number of demo TB events", 20, 250, 80, 10)
        days = st.slider("Spread across (days)", 7, 120, 30, 1)
        spike_area = st.selectbox("Spike area (cluster hotspot)", ["Rivers|Port Harcourt", "Rivers|Obio/Akpor", "Lagos|Ikeja", "Kano|Municipal"])
        spike_mult = st.slider("Spike strength", 1, 6, 3, 1)

    with colB:
        if st.button("✅ Generate demo data", type="primary"):
            generate_demo_data(fid, n_events=n_events, days=days, spike=spike_area, spike_strength=spike_mult)
            st.success("Demo data generated ✅ Now check Outbreak Analytics / Patients / Adherence / Reports.")

        if st.button("🧹 Clear ALL facility data (reset)"):
            # clear for this facility only
            for tbl in ["events", "dots_daily", "adherence", "patients", "docking_queue"]:
                try:
                    supa_delete_where(tbl, "facility_id", fid)
                except Exception:
                    pass
            st.success("Facility data cleared ✅")


def module_patients():
    st.header("Patients")
    fid = st.session_state["facility_id"]

    st.subheader("Register / Select Patient")
    colA, colB = st.columns(2)
    with colA:
        full_name = st.text_input("Patient name", placeholder="e.g., John Doe")
        age = st.number_input("Age (years)", min_value=0, max_value=120, value=30, step=1)
        sex = st.selectbox("Sex", ["Male", "Female", "Other"])
        nationality = st.text_input("Nationality", value="Nigerian")
    with colB:
        weight = st.number_input("Weight (kg)", min_value=0.0, max_value=250.0, value=65.0, step=0.1)
        height = st.number_input("Height (cm)", min_value=0, max_value=250, value=170, step=1)
        religion = st.selectbox("Religion", ["Christianity", "Islam", "Other", "Prefer not to say"])

    if st.button("Save patient", type="primary"):
        if not full_name.strip():
            st.error("Patient name is required.")
            st.stop()
        pid = make_code("PT")
        supa_insert("patients", {
            "patient_id": pid,
            "facility_id": fid,
            "full_name": full_name.strip(),
            "age": int(age),
            "sex": sex,
            "weight_kg": float(weight),
            "height_cm": int(height),
            "nationality": nationality.strip(),
            "religion": religion,
            "created_at": now_iso(),
        })
        st.success(f"Saved patient ✅ ID: {pid}")

    st.divider()
    dfp = supa_select("patients", filters={"facility_id": fid}, limit=1000, order_col="created_at", desc=True)
    if dfp.empty:
        st.info("No patients yet. Add one above or generate demo data.")
        return

    st.dataframe(dfp, use_container_width=True, hide_index=True)


def module_diagnosis():
    st.header("Digital Diagnosis (Obj 2) — Explainable Clinical AI")
    fid = st.session_state["facility_id"]

    dfp = supa_select("patients", filters={"facility_id": fid}, limit=1000, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Create at least one patient first (Patients page) or use Demo Data Generator.")
        return

    patient_label = dfp["patient_id"] + " — " + dfp["full_name"].astype(str)
    chosen = st.selectbox("Select patient", patient_label.tolist())
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("Symptoms & Risk factors")
    c1, c2 = st.columns(2)
    with c1:
        symptom_sel = []
        for s, _ in SYMPTOMS:
            if st.checkbox(s, value=False, key=f"sym_{s}"):
                symptom_sel.append(s)
    with c2:
        risk_sel = []
        for r, _ in RISKS:
            if st.checkbox(r, value=False, key=f"risk_{r}"):
                risk_sel.append(r)

    symptom_boost = sum([w for (s, w) in SYMPTOMS if s in symptom_sel]) + sum([w for (r, w) in RISKS if r in risk_sel])
    symptom_boost = min(symptom_boost, 0.35)

    st.subheader("Tests")
    colA, colB, colC = st.columns(3)
    with colA:
        gx = st.selectbox("GeneXpert", ["Not done", "Positive", "Negative"])
    with colB:
        smear = st.selectbox("Smear microscopy", ["Not done", "Positive", "Negative"])
    with colC:
        cxr = st.selectbox("CXR suggestive", ["Not done", "Positive", "Negative"])

    pretest = st.slider("Pre-test probability (setting)", 0.01, 0.80, 0.20, 0.01)
    out = diagnosis_probability(pretest, symptom_boost, {"GeneXpert": gx, "Smear microscopy": smear, "CXR suggestive": cxr})

    st.markdown('<div class="ohih-ok"><b>TB probability:</b> {:.1f}% &nbsp;&nbsp; <b>Category:</b> {}<br/>{}</div>'.format(
        100*out["prob"], out["category"], out["advice"]
    ), unsafe_allow_html=True)

    with st.expander("Explainable AI reasoning"):
        for line in out["explain"]:
            st.write("• " + line)

    st.subheader("Location for surveillance")
    col1, col2 = st.columns(2)
    with col1:
        state = st.text_input("State", value="Rivers")
        lga = st.text_input("LGA/Area", value="Port Harcourt")
    with col2:
        lat = st.number_input("Latitude (optional)", value=0.0, step=0.0001, format="%.4f")
        lon = st.number_input("Longitude (optional)", value=0.0, step=0.0001, format="%.4f")

    notes = st.text_area("Clinical notes (optional)", height=90)

    if st.button("Save event to surveillance", type="primary"):
        supa_insert("events", {
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
        })
        st.success("Event saved ✅ Now view Outbreak Analytics.")


def module_microscopy_ai():
    st.header("Microscopy AI (A) — Prototype")
    st.caption("Hackathon MVP uses a lightweight vision score. Next phase: CNN trained on labeled AFB microscopy images.")

    img = st.file_uploader("Upload microscopy image (JPG/PNG)", type=["jpg", "jpeg", "png"])
    if not img:
        st.info("Upload an image to test the prototype scoring.")
        return

    b = img.getbuffer().tobytes()
    r = microscopy_score(b)

    st.markdown('<div class="ohih-ok"><b>Suspicion score:</b> {:.1f}%<br/><b>Label:</b> {}<br/><span class="ohih-small">contrast={:.3f}, dark_density={:.3f}</span></div>'.format(
        r["score_pct"], r["label"], r["contrast"], r["dark_density"]
    ), unsafe_allow_html=True)

    st.image(b, caption="Uploaded microscopy image", use_container_width=True)


def module_adherence_dots():
    st.header("Treatment Adherence + DOTS (B)")
    fid = st.session_state["facility_id"]

    dfp = supa_select("patients", filters={"facility_id": fid}, limit=1000, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Create patients first (Patients page) or generate demo data.")
        return

    patient_label = dfp["patient_id"] + " — " + dfp["full_name"].astype(str)
    chosen = st.selectbox("Select patient", patient_label.tolist())
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("DOTS daily tick (today)")
    today = dt.date.today().isoformat()
    dose_taken = st.checkbox("Dose taken today", value=True)
    note = st.text_input("Note (optional)", value="")

    if st.button("Save today DOTS tick", type="primary"):
        supa_upsert("dots_daily", {
            "facility_id": fid,
            "patient_id": patient_id,
            "date": today,
            "dose_taken": bool(dose_taken),
            "note": note.strip(),
            "created_at": now_iso(),
        }, on_conflict="facility_id,patient_id,date")
        st.success("Saved DOTS tick ✅")

    dfd = supa_select("dots_daily", filters={"facility_id": fid, "patient_id": patient_id}, limit=2000, order_col="date", desc=True)
    if dfd.empty:
        st.info("No DOTS records yet for this patient.")
        return

    # compute missed in last 7/28
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
    colA, colB, colC, colD = st.columns(4)
    colA.metric("Missed doses (7d)", missed_7)
    colB.metric("Adherence (7d)", f"{adh7:.1f}%")
    colC.metric("Missed doses (28d)", missed_28)
    colD.metric("Adherence (28d)", f"{adh28:.1f}%")

    streak = st.selectbox("Longest missed streak (self-reported/observed)", STREAK_OPTIONS, index=0)
    completed = st.checkbox("Completed regimen", value=False)

    # cumulative since first dots date
    start = dfd["date"].min().date()
    total_days = (dt.date.today() - start).days + 1
    total_expected = max(1, total_days)
    total_taken = int(dfd["dose_taken"].astype(bool).sum())
    total_missed = max(0, total_expected - total_taken)
    cumulative_pct = 100.0 * total_taken / total_expected

    flag = missed_over_25pct(missed_28)
    risk = risk_model(missed_28, streak, cumulative_pct, completed)

    st.markdown(
        '<div class="{}"><b>Resistance/Failure flag (>25% missed in 28d):</b> {}<br/>'
        '<b>Risk score:</b> {:.1f}/100 &nbsp; <b>Risk level:</b> {}<br/>{}</div>'.format(
            "ohih-warn" if flag or risk["risk_category"] in ["High", "Very High"] else "ohih-ok",
            "✅ HIGH RISK" if flag else "No",
            risk["risk_score"], risk["risk_category"], risk["message"]
        ),
        unsafe_allow_html=True
    )

    if st.button("Save adherence snapshot", type="primary"):
        supa_insert("adherence", {
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
        st.success("Saved adherence snapshot ✅")

    with st.expander("DOTS table"):
        show = dfd.copy()
        show["date"] = show["date"].dt.date.astype(str)
        st.dataframe(show.sort_values("date", ascending=False), use_container_width=True, hide_index=True)


def module_repurposing():
    st.header("Drug Repurposing (Obj 1)")
    st.caption("Hackathon MVP uses a curated shortlist. Next phase: integrate SwissTargetPrediction/DrugBank pipelines.")
    fid = st.session_state["facility_id"]

    targets = sorted(list({r["target"] for r in REPURPOSE_DB}))
    target = st.selectbox("Select TB target", targets)

    df = pd.DataFrame([r for r in REPURPOSE_DB if r["target"] == target])
    st.dataframe(df, use_container_width=True, hide_index=True)

    picks = st.multiselect("Select drugs to send to docking queue", df["drug_name"].tolist())
    notes = st.text_input("Notes (optional)", value="repurposing shortlist")

    if st.button("Send selected to docking queue", type="primary"):
        if not picks:
            st.error("Select at least one drug.")
            st.stop()
        for name in picks:
            row = df[df["drug_name"] == name].iloc[0].to_dict()
            supa_insert("docking_queue", {
                "queue_id": make_code("DQ"),
                "facility_id": fid,
                "timestamp": now_iso(),
                "target": row["target"],
                "drug_name": row["drug_name"],
                "drug_id": row.get("drug_id", ""),
                "notes": notes.strip(),
            })
        st.success("Queued ✅ Now go to Docking (Obj 3).")


def module_docking():
    st.header("Docking (Obj 3) + Interpretation (C)")
    st.caption("Cloud: Demo docking. Local laptop: real Vina docking (recommended for validation).")
    fid = st.session_state["facility_id"]

    dfq = supa_select("docking_queue", filters={"facility_id": fid}, limit=500, order_col="timestamp", desc=True)
    if dfq.empty:
        st.info("Docking queue is empty. Add drugs from Repurposing or generate demo data.")
    else:
        st.subheader("Docking Queue")
        st.dataframe(dfq[["timestamp", "target", "drug_name", "drug_id", "notes"]], use_container_width=True, hide_index=True)

    st.subheader("Demo docking (instant)")
    drug_name = st.text_input("Drug (for demo scoring)", value=(dfq.iloc[0]["drug_name"] if not dfq.empty else "Demo drug"))

    def demo_affinity(name: str) -> float:
        base = (sum(ord(c) for c in name) % 60) / 10.0
        return -6.0 - base  # ~ -6 to -11.9

    if st.button("Run DEMO docking", type="primary"):
        aff = demo_affinity(drug_name)
        st.success("Demo docking complete ✅")
        st.write(f"**Affinity (demo):** {aff:.2f} kcal/mol")

        if aff <= -9.0:
            interp = "Strong (screening hit)"
            rec = "Proceed to rescoring, ADMET, and lab validation."
        elif aff <= -7.5:
            interp = "Moderate"
            rec = "Consider optimization/controls and re-docking."
        else:
            interp = "Weak"
            rec = "Low priority unless supported by other evidence."

        st.markdown(f"**Interpretation:** {interp}\n\n**Next step:** {rec}")

    st.divider()
    st.markdown("### Real docking (local laptop only)")
    st.markdown(
        """
For real AutoDock Vina docking, run the app locally on your laptop (Windows) where `vina.exe` exists.
Streamlit Cloud does not reliably support native docking binaries.
        """
    )


def module_outbreak():
    st.header("Outbreak Detection & Analytics (Obj 4)")
    fid = st.session_state["facility_id"]

    dfe = supa_select("events", filters={"facility_id": fid}, limit=5000, order_col="timestamp", desc=True)
    if dfe.empty:
        st.info("No events yet. Save diagnosis events or generate demo data.")
        return

    dfe["timestamp"] = pd.to_datetime(dfe["timestamp"], errors="coerce")
    dfe = dfe.dropna(subset=["timestamp"])
    dfe["date"] = dfe["timestamp"].dt.date

    st.subheader("Trend (daily suspected/confirmed TB events)")
    daily = dfe.groupby("date").size().reset_index(name="cases").sort_values("date")
    st.line_chart(daily.set_index("date")["cases"])

    st.subheader("Spike alerts (simple heuristic)")
    # compare last 7 days vs previous 7 days, by area
    end = dt.date.today()
    last7_start = end - dt.timedelta(days=6)
    prev7_start = end - dt.timedelta(days=13)
    prev7_end = end - dt.timedelta(days=7)

    recent = dfe[(dfe["date"] >= last7_start) & (dfe["date"] <= end)]
    prev = dfe[(dfe["date"] >= prev7_start) & (dfe["date"] <= prev7_end)]

    def by_area(df):
        if df.empty:
            return pd.DataFrame(columns=["state", "lga_or_area", "n"])
        return df.groupby(["state", "lga_or_area"]).size().reset_index(name="n")

    rA = by_area(recent)
    pA = by_area(prev)

    alert = rA.merge(pA, on=["state", "lga_or_area"], how="left", suffixes=("_recent", "_prev")).fillna(0)
    alert["ratio"] = alert.apply(lambda x: (x["n_recent"] / max(1.0, x["n_prev"])), axis=1)
    alert = alert.sort_values(["ratio", "n_recent"], ascending=[False, False])

    st.dataframe(alert.head(10), use_container_width=True, hide_index=True)
    if not alert.empty and (alert.iloc[0]["n_recent"] >= 5 and alert.iloc[0]["ratio"] >= 2.0):
        top = alert.iloc[0]
        st.warning(f"Potential cluster: {top['state']} / {top['lga_or_area']} (ratio {top['ratio']:.2f}, recent {int(top['n_recent'])})")

    st.subheader("Heatmap")
    if not MAP_OK:
        st.error("Mapping libraries not installed. Add folium and streamlit-folium to requirements.txt.")
        return

    # Use only valid coords
    coords = dfe[(dfe["lat"].abs() > 0) & (dfe["lon"].abs() > 0)][["lat", "lon", "tb_probability"]].copy()
    if coords.empty:
        st.info("No valid lat/lon events. Enter coordinates in Diagnosis or use demo data.")
        return

    m = folium.Map(location=[coords["lat"].mean(), coords["lon"].mean()], zoom_start=7)
    heat_data = [[row["lat"], row["lon"], float(row["tb_probability"])] for _, row in coords.iterrows()]
    HeatMap(heat_data, radius=18, blur=14, max_zoom=10).add_to(m)
    st_folium(m, width=1100, height=520)


def module_reports():
    st.header("Reports & Admin Export (D)")
    fid = st.session_state["facility_id"]
    role = st.session_state.get("user_role", "standard")

    dfe = supa_select("events", filters={"facility_id": fid}, limit=5000, order_col="timestamp", desc=True)
    dfp = supa_select("patients", filters={"facility_id": fid}, limit=5000, order_col="created_at", desc=True)
    dfd = supa_select("dots_daily", filters={"facility_id": fid}, limit=5000, order_col="date", desc=True)
    dfa = supa_select("adherence", filters={"facility_id": fid}, limit=5000, order_col="timestamp", desc=True)
    dfq = supa_select("docking_queue", filters={"facility_id": fid}, limit=5000, order_col="timestamp", desc=True)

    st.subheader("Facility downloads")
    col1, col2, col3, col4, col5 = st.columns(5)

    def dl(df, name, col):
        with col:
            st.download_button(
                f"Download {name}.csv",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"{name}.csv",
                mime="text/csv",
                use_container_width=True
            )

    dl(dfp, "patients", col1)
    dl(dfe, "events", col2)
    dl(dfd, "dots_daily", col3)
    dl(dfa, "adherence", col4)
    dl(dfq, "docking_queue", col5)

    st.divider()
    st.subheader("Patient report")
    if dfp.empty:
        st.info("No patients.")
        return

    patient_label = dfp["patient_id"] + " — " + dfp["full_name"].astype(str)
    chosen = st.selectbox("Select patient for report", patient_label.tolist(), key="rep_patient")
    patient_id = chosen.split(" — ")[0].strip()

    p = dfp[dfp["patient_id"] == patient_id].iloc[0].to_dict()
    a = dfa[dfa["patient_id"] == patient_id].head(1)
    lastA = a.iloc[0].to_dict() if not a.empty else {}

    report = []
    report.append(f"OHIH TB Platform — Patient Report")
    report.append(f"Facility: {st.session_state['facility_name']}")
    report.append(f"Generated: {now_iso()}")
    report.append("")
    report.append(f"Patient ID: {patient_id}")
    report.append(f"Name: {p.get('full_name','')}")
    report.append(f"Age/Sex: {p.get('age','')} / {p.get('sex','')}")
    report.append(f"Weight/Height: {p.get('weight_kg','')} kg / {p.get('height_cm','')} cm")
    report.append(f"Nationality/Religion: {p.get('nationality','')} / {p.get('religion','')}")
    report.append("")
    if lastA:
        report.append("Latest adherence snapshot:")
        report.append(f"- Missed 7d: {lastA.get('missed_7','')}, Adh7: {lastA.get('adh_7_pct','')}%")
        report.append(f"- Missed 28d: {lastA.get('missed_28','')}, Adh28: {lastA.get('adh_28_pct','')}%")
        report.append(f"- Flag >25% missed: {lastA.get('flag_over_25pct','')}")
        report.append(f"- Risk: {lastA.get('risk_category','')} (score {lastA.get('risk_score','')})")
        report.append(f"- Completed: {lastA.get('completed','')}")
    else:
        report.append("No adherence snapshot saved yet.")

    report_txt = "\n".join(report)
    st.text_area("Report preview", report_txt, height=280)
    st.download_button("Download patient_report.txt", data=report_txt.encode("utf-8"), file_name="patient_report.txt", mime="text/plain")

    st.divider()
    st.subheader("Admin: export ALL facilities (central data)")
    if role != "admin":
        st.info("Admin-only. Log in as admin to export all facilities data.")
        return

    st.warning("Admin export returns data across all registered facilities. Use responsibly.")
    if st.button("Generate ALL-facilities export", type="primary"):
        all_fac = supa_select("facilities", limit=5000)
        all_pat = supa_select("patients", limit=50000)
        all_evt = supa_select("events", limit=50000)
        all_dot = supa_select("dots_daily", limit=50000)
        all_adh = supa_select("adherence", limit=50000)
        all_dq = supa_select("docking_queue", limit=50000)

        st.success("Loaded central datasets ✅")
        st.download_button("Download ALL_facilities.csv", all_fac.to_csv(index=False).encode("utf-8"), "ALL_facilities.csv", "text/csv")
        st.download_button("Download ALL_patients.csv", all_pat.to_csv(index=False).encode("utf-8"), "ALL_patients.csv", "text/csv")
        st.download_button("Download ALL_events.csv", all_evt.to_csv(index=False).encode("utf-8"), "ALL_events.csv", "text/csv")
        st.download_button("Download ALL_dots_daily.csv", all_dot.to_csv(index=False).encode("utf-8"), "ALL_dots_daily.csv", "text/csv")
        st.download_button("Download ALL_adherence.csv", all_adh.to_csv(index=False).encode("utf-8"), "ALL_adherence.csv", "text/csv")
        st.download_button("Download ALL_docking_queue.csv", all_dq.to_csv(index=False).encode("utf-8"), "ALL_docking_queue.csv", "text/csv")


# -----------------------------
# APP ENTRY
# -----------------------------
def main_app():
    sidebar_header()
    with st.sidebar:
        module = st.radio(
            "Modules",
            [
                "Home",
                "Patients",
                "Digital Diagnosis (Obj 2)",
                "Microscopy AI (A)",
                "Adherence + DOTS (B)",
                "Drug Repurposing (Obj 1)",
                "Docking + Interpretation (Obj 3 + C)",
                "Outbreak Analytics (Obj 4)",
                "Reports & Admin Export (D)",
            ],
        )

        st.markdown("---")
        if st.button("Logout"):
            st.session_state["logged_in"] = False
            st.session_state["auth_step"] = 1
            st.rerun()

    if module == "Home":
        module_home()
    elif module == "Patients":
        module_patients()
    elif module.startswith("Digital Diagnosis"):
        module_diagnosis()
    elif module.startswith("Microscopy"):
        module_microscopy_ai()
    elif module.startswith("Adherence"):
        module_adherence_dots()
    elif module.startswith("Drug Repurposing"):
        module_repurposing()
    elif module.startswith("Docking"):
        module_docking()
    elif module.startswith("Outbreak"):
        module_outbreak()
    elif module.startswith("Reports"):
        module_reports()


def boot_checks():
    # minimal sanity checks for build
    if not SUPA_OK:
        st.error("Install dependency: supabase")
        st.stop()

    # ping by simple select (will error if secrets wrong)
    try:
        _ = supa_select("facilities", limit=1)
    except Exception as e:
        st.error(f"Supabase connection failed: {e}")
        st.stop()

    if not MAP_OK:
        st.warning("Heatmap libraries missing. Outbreak heatmap will not render until folium + streamlit-folium are installed.")


# Run
boot_checks()

if not st.session_state.get("logged_in"):
    onboarding_ui()
else:
    main_app()
