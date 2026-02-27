import os
import base64
import hashlib
import random
import datetime as dt
from typing import Dict, Any, Optional

import pandas as pd
import streamlit as st

# Supabase dependency
SUPA_OK = True
try:
    from supabase import create_client
except Exception:
    SUPA_OK = False


# =========================
# UI / STYLE
# =========================
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
hr{ border: none; border-top: 1px solid rgba(15,23,42,0.12); margin: 10px 0;}
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

APP_VERSION = "OHIH TB Platform — Hospital-ready MVP (Clean single-file)"

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


# =========================
# SECRETS (robust)
# =========================
def safe_secret(name: str, default: str = "") -> str:
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets.get(name))
    except Exception:
        pass
    return os.getenv(name, default)

SUPABASE_URL = safe_secret("SUPABASE_URL", "")
SUPABASE_ANON_KEY = safe_secret("SUPABASE_ANON_KEY", "") or safe_secret("SUPABASE_KEY", "")
APP_PEPPER = safe_secret("APP_PEPPER", "CHANGE_ME_PEPPER")
ORGANIZER_MASTER_KEY = safe_secret("ORGANIZER_MASTER_KEY", "")

st.info(f"Connected SUPABASE_URL: {SUPABASE_URL}")

def supabase_ready() -> bool:
    return SUPA_OK and bool(SUPABASE_URL) and bool(SUPABASE_ANON_KEY)

def get_supa():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# =========================
# UTILITIES
# =========================
def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")

def make_code(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"

def hash_password(password: str) -> str:
    raw = (APP_PEPPER + password).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def gen_facility_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(10))

def b64_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# =========================
# SUPABASE HELPERS
# =========================
def db_select(table: str, filters: Dict[str, Any] = None, limit: int = 50000, order_col: str = None, desc: bool = True) -> pd.DataFrame:
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

def db_insert(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    supa = get_supa()
    res = supa.table(table).insert(row).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)
    return (res.data or [{}])[0]

def db_upsert(table: str, row: Dict[str, Any], on_conflict: Optional[str] = None) -> None:
    supa = get_supa()
    res = supa.table(table).upsert(row, on_conflict=on_conflict).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)


# =========================
# DB SETUP SQL (in-app)
# =========================
SETUP_SQL = r"""
-- Run this in Supabase → SQL Editor (once)

create table if not exists public.facilities (
  facility_id text primary key,
  facility_name text not null,
  facility_reg text unique not null,
  facility_password_hash text not null,
  created_at text
);

create table if not exists public.users (
  user_id text primary key,
  facility_id text not null references public.facilities(facility_id),
  full_name text not null,
  staff_id text not null,
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
  tb_probability float,
  category text,
  genexpert text,
  smear text,
  cxr text,
  notes text,

  comorbid_dm boolean,
  comorbid_htn boolean,
  comorbid_asthma boolean,
  comorbid_ckd boolean,
  comorbid_cld boolean,
  comorbid_hiv boolean,
  comorbid_other text,

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
  missed_7 int,
  missed_28 int,
  missed_streak text,
  completed boolean,
  adh_7_pct float,
  adh_28_pct float,
  flag_over_25pct boolean,
  risk_level text,
  notes text
);

-- Optional: block deletes (recommended)
revoke delete on public.facilities from anon, authenticated;
revoke delete on public.users from anon, authenticated;
revoke delete on public.patients from anon, authenticated;
revoke delete on public.events from anon, authenticated;
revoke delete on public.dots_daily from anon, authenticated;
revoke delete on public.adherence from anon, authenticated;
"""

def db_setup_page():
    st.subheader("DB Setup / Fix missing columns")
    st.caption("If you see errors like “Could not find column …”, run this SQL in Supabase → SQL Editor.")
    st.code(SETUP_SQL, language="sql")


# =========================
# DIAGNOSIS (simple, explainable)
# =========================
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
    ("Fatigue", 0.03),
]
RISKS = [
    ("Known TB contact", 0.12),
    ("HIV positive", 0.12),
    ("Previous TB treatment", 0.10),
    ("Diabetes", 0.04),
    ("Severe malnutrition", 0.07),
    ("Smoker", 0.03),
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
        advice = "Treat per guideline, assess HIV, begin contact tracing."
    elif p >= 0.70:
        category = "HIGH probability"
        advice = "Urgent confirmatory testing (GeneXpert). Consider empiric treatment if severe."
    elif p >= 0.35:
        category = "MODERATE probability"
        advice = "Order GeneXpert/microscopy; close follow-up."
    elif p >= 0.15:
        category = "LOW–MODERATE probability"
        advice = "Monitor and re-test if symptoms persist."
    else:
        category = "LOW probability"
        advice = "TB unlikely. Investigate other causes."

    return {"prob": float(p), "category": category, "advice": advice, "explain": explain}


# =========================
# ADHERENCE SUPPORT
# =========================
MISSED_STREAK_OPTIONS = ["0 days", "1–2 days", "3–6 days", "1 week", "2 weeks", "3 weeks", "1 month or more"]

def compute_adherence_percent(missed: int, window: int) -> float:
    window = max(1, int(window))
    missed = max(0, int(missed))
    return max(0.0, 100.0 * (1.0 - missed / window))

def missed_over_25pct(missed_28: int) -> bool:
    return int(missed_28) >= 8  # >25% of 28

def risk_level(flag_over_25: bool, missed_streak: str, completed: bool) -> str:
    if completed and not flag_over_25:
        return "Low (completed)"
    if flag_over_25:
        return "High (risk of failure/resistance)"
    if missed_streak in ("2 weeks", "3 weeks", "1 month or more"):
        return "High"
    if missed_streak in ("1 week", "3–6 days"):
        return "Moderate"
    return "Low"

def make_ics_daily_reminders(summary="TB Drugs Reminder", hour1=8, hour2=14) -> bytes:
    uid1 = f"{random.randint(100000,999999)}@ohih"
    uid2 = f"{random.randint(100000,999999)}@ohih"
    now = dt.datetime.now()
    dtstart1 = now.replace(hour=hour1, minute=0, second=0, microsecond=0)
    dtstart2 = now.replace(hour=hour2, minute=0, second=0, microsecond=0)

    def fmt(x): return x.strftime("%Y%m%dT%H%M%S")
    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//OHIH//TB Reminders//EN
BEGIN:VEVENT
UID:{uid1}
DTSTAMP:{fmt(now)}
DTSTART:{fmt(dtstart1)}
RRULE:FREQ=DAILY
SUMMARY:{summary} (08:00)
END:VEVENT
BEGIN:VEVENT
UID:{uid2}
DTSTAMP:{fmt(now)}
DTSTART:{fmt(dtstart2)}
RRULE:FREQ=DAILY
SUMMARY:{summary} (14:00)
END:VEVENT
END:VCALENDAR
"""
    return ics.encode("utf-8")


# =========================
# SESSION STATE
# =========================
def ss_init():
    st.session_state.setdefault("onboard_step", 1)  # 1..3 only
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("facility_id", None)
    st.session_state.setdefault("facility_name", None)
    st.session_state.setdefault("facility_reg", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("staff_id", None)
    st.session_state.setdefault("profession", None)
    st.session_state.setdefault("user_role", "standard")
    st.session_state.setdefault("organizer_mode", False)

    # critical: hold generated password until user confirms saved
    st.session_state.setdefault("pending_facility_password", "")
    st.session_state.setdefault("pending_facility_reg", "")
    st.session_state.setdefault("pending_facility_id", "")

ss_init()


# =========================
# ORGANIZER RESET (built in)
# =========================
def organizer_reset_facility_password(facility_reg: str, new_password: str) -> None:
    if not facility_reg.strip():
        raise ValueError("facility_reg required")
    if not new_password.strip():
        raise ValueError("new_password required")
    supa = get_supa()
    res = supa.table("facilities").update(
        {"facility_password_hash": hash_password(new_password.strip())}
    ).eq("facility_reg", facility_reg.strip()).execute()
    if getattr(res, "error", None):
        raise RuntimeError(res.error.message)


# =========================
# ONBOARDING (3 pages only)
# =========================
def onboarding():
    hero("OHIH TB Platform", "Hospital-ready MVP: multi-facility • diagnosis • adherence • central upload", badge="DEPLOY")

    step = st.session_state["onboard_step"]
    cols = st.columns(3)
    labels = ["1) Facility", "2) Staff", "3) Enter Platform"]
    for i, c in enumerate(cols, start=1):
        with c:
            st.write(("✅ " if step > i else "➡️ " if step == i else "• ") + labels[i-1])

    # -------- STEP 1: FACILITY --------
    if step == 1:
        st.subheader("Facility Sign-in / Register")

        colA, colB = st.columns(2)
        with colA:
            facility_name = st.text_input("Facility Name (for new registration)", placeholder="e.g., RSUTH")
        with colB:
            facility_reg = st.text_input("Facility Registration Number", placeholder="e.g., RSUTH-CH-001")

        mode = st.radio("Choose", ["Register new facility", "Sign in to existing facility"], horizontal=True)
        facility_pw = None
        if mode == "Sign in to existing facility":
            facility_pw = st.text_input("Facility password", type="password")

        # If registration has already happened for this facility_reg,
        # show password and wait for user confirmation before moving on.
        if (mode == "Register new facility"
            and st.session_state["pending_facility_reg"] == facility_reg.strip()
            and st.session_state["pending_facility_password"]):

            st.success("Facility registered ✅")
            st.markdown(
                f'<div class="warn"><b>IMPORTANT:</b> Save this password now (it will not be shown again).<br/>'
                f'<b>Password:</b> <code>{st.session_state["pending_facility_password"]}</code></div>',
                unsafe_allow_html=True
            )
            if st.button("I have saved the password → Continue", type="primary"):
                st.session_state["facility_id"] = st.session_state["pending_facility_id"]
                st.session_state["facility_name"] = facility_name.strip()
                st.session_state["facility_reg"] = facility_reg.strip()
                st.session_state["onboard_step"] = 2

                st.session_state["pending_facility_password"] = ""
                st.session_state["pending_facility_reg"] = ""
                st.session_state["pending_facility_id"] = ""
                st.rerun()
            st.stop()

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
                    st.error("Enter Facility Name.")
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
                    st.error(f"Facility save failed: {e}")
                    db_setup_page()
                    st.stop()

                # Hold password until user confirms saved
                st.session_state["pending_facility_password"] = pw_plain
                st.session_state["pending_facility_reg"] = facility_reg.strip()
                st.session_state["pending_facility_id"] = fid

                st.success("Facility registered ✅")
                st.markdown(
                    f'<div class="warn"><b>IMPORTANT:</b> Save this password now (it will not be shown again).<br/>'
                    f'<b>Password:</b> <code>{pw_plain}</code></div>',
                    unsafe_allow_html=True
                )
                if st.button("I have saved the password → Continue", type="primary"):
                    st.session_state["facility_id"] = fid
                    st.session_state["facility_name"] = facility_name.strip()
                    st.session_state["facility_reg"] = facility_reg.strip()
                    st.session_state["onboard_step"] = 2

                    st.session_state["pending_facility_password"] = ""
                    st.session_state["pending_facility_reg"] = ""
                    st.session_state["pending_facility_id"] = ""
                    st.rerun()
                st.stop()

            # Sign in
            else:
                if df.empty:
                    st.error("Facility not found. Use Register or check number.")
                    st.stop()
                if not facility_pw:
                    st.error("Enter facility password.")
                    st.stop()

                row = df.iloc[0].to_dict()
                if hash_password(facility_pw.strip()) != (row.get("facility_password_hash") or ""):
                    st.error("Wrong facility password.")
                    st.stop()

                st.session_state["facility_id"] = row["facility_id"]
                st.session_state["facility_name"] = row["facility_name"]
                st.session_state["facility_reg"] = row["facility_reg"]
                st.session_state["onboard_step"] = 2
                st.rerun()

        st.divider()
        st.subheader("Organizer tools (export ALL + reset facility password)")
        master = st.text_input("Organizer master key", type="password")

        if st.button("Unlock organizer mode"):
            if ORGANIZER_MASTER_KEY and master == ORGANIZER_MASTER_KEY:
                st.session_state["organizer_mode"] = True
                st.success("Organizer mode unlocked ✅")
            else:
                st.error("Invalid organizer key.")

        with st.expander("🔑 Forgot facility password? (Organizer reset)"):
            st.markdown('<div class="warn"><b>Warning:</b> This resets a facility password immediately.</div>', unsafe_allow_html=True)
            reg_to_reset = st.text_input("Facility Registration Number to reset")
            new_pw = st.text_input("New facility password (you choose)", type="password")
            confirm_pw = st.text_input("Confirm new password", type="password")
            if st.button("Reset facility password", type="primary"):
                if not (ORGANIZER_MASTER_KEY and master == ORGANIZER_MASTER_KEY):
                    st.error("Organizer key required to reset.")
                    st.stop()
                if new_pw != confirm_pw:
                    st.error("Passwords do not match.")
                    st.stop()
                try:
                    organizer_reset_facility_password(reg_to_reset, new_pw)
                    st.success(f"Reset done ✅ Facility {reg_to_reset.strip()} can sign in with the new password.")
                except Exception as e:
                    st.error(f"Reset failed: {e}")

    # -------- STEP 2: STAFF --------
    elif step == 2:
        st.subheader("Staff Sign-in (within facility)")
        st.info(f"Facility: **{st.session_state['facility_name']}**")

        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Staff full name")
            staff_id = st.text_input("Staff ID")
            profession = st.selectbox("Profession", ["Doctor","Nurse","Lab Scientist","Pharmacist","Data Officer","Community Health Worker","Other"])
            role = st.selectbox("Role", ["standard", "admin"], help="Admin can export facility data.")
        with col2:
            face = st.file_uploader("Optional: Upload face photo (JPG/PNG)", type=["jpg","jpeg","png"])
            st.caption("MVP stores image for identity check. Not biometric-grade.")

        back, cont = st.columns(2)
        with back:
            if st.button("← Back"):
                st.session_state["onboard_step"] = 1
                st.rerun()
        with cont:
            if st.button("Continue →", type="primary"):
                if not full_name.strip() or not staff_id.strip():
                    st.error("Enter staff name and staff ID.")
                    st.stop()

                face_b64 = ""
                if face:
                    face_b64 = b64_bytes(face.getbuffer().tobytes())

                uid = make_code("USR")
                try:
                    db_upsert("users", {
                        "user_id": uid,
                        "facility_id": st.session_state["facility_id"],
                        "full_name": full_name.strip(),
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

                st.session_state["user_name"] = full_name.strip()
                st.session_state["staff_id"] = staff_id.strip()
                st.session_state["profession"] = profession
                st.session_state["user_role"] = role
                st.session_state["onboard_step"] = 3
                st.rerun()

    # -------- STEP 3: ENTER --------
    else:
        st.subheader("Enter Platform")
        st.markdown(
            f"""
            <div class="card">
              <b>Facility:</b> {st.session_state['facility_name']}<br/>
              <b>User:</b> {st.session_state['user_name']} ({st.session_state['profession']})<br/>
              <b>Role:</b> {st.session_state['user_role']}<br/>
              <span class="small">Central upload: ✅ Supabase</span>
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


# =========================
# MAIN APP PAGES
# =========================
def sidebar_nav() -> str:
    with st.sidebar:
        st.markdown("### OHIH TB Platform")
        st.write(f"**Facility:** {st.session_state['facility_name']}")
        st.write(f"**User:** {st.session_state['user_name']}")
        st.write(f"**Role:** {st.session_state['user_role']}")
        if st.session_state.get("organizer_mode"):
            st.success("Organizer mode: ON")

        st.markdown("---")
        page = st.radio("Menu", ["Home", "Patients", "Diagnosis", "Adherence + DOTS", "Reports", "DB Setup Help"])
        st.markdown("---")
        if st.button("Logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            ss_init()
            st.rerun()
        return page


def home_page():
    hero("OHIH TB Platform", "Stable MVP workflow: register patient → diagnosis → DOTS/adherence → export.", badge="LIVE")
    st.markdown('<div class="ok"><b>Central upload:</b> All saves go to Supabase immediately.</div>', unsafe_allow_html=True)
    st.subheader("Daily reminders (8am & 2pm)")
    st.caption("Streamlit cannot push notifications if the app is closed. Best option: download calendar reminders.")
    ics = make_ics_daily_reminders()
    st.download_button("⬇️ Download daily reminders (Calendar .ics)", data=ics, file_name="tb_drug_reminders.ics", mime="text/calendar")


def patients_page():
    st.header("Patients (Registration + facility-only list)")
    fid = st.session_state["facility_id"]

    with st.expander("➕ Register new patient", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Full name *")
            age = st.number_input("Age", 0, 120, 30)
            sex = st.selectbox("Sex", ["Male", "Female", "Other"])
            weight_kg = st.number_input("Weight (kg)", 0.0, 300.0, 65.0, step=0.1)
            height_cm = st.number_input("Height (cm)", 0, 250, 170)
            nationality = st.text_input("Nationality", value="Nigerian")
            religion = st.text_input("Religion", value="")
        with col2:
            phone = st.text_input("Phone number")
            email = st.text_input("Email")
            address = st.text_area("Address", height=90)
            st.markdown("**Next of kin**")
            nok_name = st.text_input("NOK name")
            nok_phone = st.text_input("NOK phone")
            nok_email = st.text_input("NOK email")

        st.markdown("#### Confirmation summary (check before saving)")
        st.markdown(
            f"""
            <div class="card">
            <b>Name:</b> {full_name}<br/>
            <b>Age/Sex:</b> {age} / {sex}<br/>
            <b>Wt/Ht:</b> {weight_kg} kg / {height_cm} cm<br/>
            <b>Nationality:</b> {nationality}<br/>
            <b>Religion:</b> {religion}<hr/>
            <b>Phone:</b> {phone}<br/>
            <b>Email:</b> {email}<br/>
            <b>Address:</b> {address}<hr/>
            <b>NOK Name:</b> {nok_name}<br/>
            <b>NOK Phone:</b> {nok_phone}<br/>
            <b>NOK Email:</b> {nok_email}
            </div>
            """,
            unsafe_allow_html=True
        )

        if st.button("✅ Save patient", type="primary"):
            if not full_name.strip():
                st.error("Full name is required.")
                st.stop()
            pid = make_code("PT")
            try:
                db_insert("patients", {
                    "patient_id": pid,
                    "facility_id": fid,
                    "full_name": full_name.strip(),
                    "age": int(age),
                    "sex": sex,
                    "weight_kg": float(weight_kg),
                    "height_cm": int(height_cm),
                    "nationality": nationality.strip(),
                    "religion": religion.strip(),
                    "phone": phone.strip(),
                    "email": email.strip(),
                    "address": address.strip(),
                    "next_of_kin_name": nok_name.strip(),
                    "next_of_kin_phone": nok_phone.strip(),
                    "next_of_kin_email": nok_email.strip(),
                    "created_at": now_iso(),
                })
                st.success(f"Saved ✅ Patient ID: {pid}")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
                st.info("This usually means DB columns missing. Open DB Setup Help and run the SQL.")
                st.stop()

    st.subheader("Patient list (this facility only)")
    try:
        df = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
        if df.empty:
            st.info("No patients yet.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Load failed: {e}")
        db_setup_page()


def diagnosis_page():
    st.header("Digital TB Diagnosis (Explainable)")
    fid = st.session_state["facility_id"]

    dfp = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Add a patient first.")
        return

    labels = (dfp["patient_id"].astype(str) + " — " + dfp["full_name"].astype(str)).tolist()
    chosen = st.selectbox("Select patient", labels)
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("Symptoms + Risk factors")
    colA, colB = st.columns(2)
    with colA:
        sym_sel = [s for s,_ in SYMPTOMS if st.checkbox(s, False)]
    with colB:
        risk_sel = [r for r,_ in RISKS if st.checkbox(r, False, key=f"risk_{r}")]

    boost = sum([w for s,w in SYMPTOMS if s in sym_sel]) + sum([w for r,w in RISKS if r in risk_sel])
    boost = min(boost, 0.35)

    st.subheader("Test inputs")
    gx = st.selectbox("GeneXpert", ["Not done","Positive","Negative"])
    smear = st.selectbox("Smear microscopy", ["Not done","Positive","Negative"])
    cxr = st.selectbox("CXR suggestive", ["Not done","Positive","Negative"])

    pretest = st.slider("Clinician pre-test probability", 0.01, 0.80, 0.20, 0.01)
    out = diagnosis_probability(pretest, boost, {"GeneXpert": gx, "Smear microscopy": smear, "CXR suggestive": cxr})

    st.markdown(
        f'<div class="ok"><b>TB probability:</b> {100*out["prob"]:.1f}% &nbsp; <b>Category:</b> {out["category"]}<br/>{out["advice"]}</div>',
        unsafe_allow_html=True
    )

    st.subheader("Chronic illnesses + allergies")
    c1, c2, c3 = st.columns(3)
    with c1:
        dm = st.checkbox("Diabetes Mellitus (DM)")
        htn = st.checkbox("Hypertension (HTN)")
        asthma = st.checkbox("Asthma/COPD")
    with c2:
        ckd = st.checkbox("Chronic Kidney Disease (CKD)")
        cld = st.checkbox("Chronic Liver Disease (CLD)")
        hiv = st.checkbox("HIV")
    with c3:
        other_comorb = st.text_input("Other chronic illness", "")
        allergy_drug = st.checkbox("Drug allergy")
        allergy_food = st.checkbox("Food allergy")
        allergy_other = st.text_input("Other allergy", "")

    notes = st.text_area("Clinical notes", height=80)

    if st.button("Save diagnosis event", type="primary"):
        try:
            db_insert("events", {
                "event_id": make_code("EV"),
                "facility_id": fid,
                "patient_id": patient_id,
                "timestamp": now_iso(),
                "tb_probability": float(out["prob"]),
                "category": out["category"],
                "genexpert": gx,
                "smear": smear,
                "cxr": cxr,
                "notes": notes.strip(),
                "comorbid_dm": bool(dm),
                "comorbid_htn": bool(htn),
                "comorbid_asthma": bool(asthma),
                "comorbid_ckd": bool(ckd),
                "comorbid_cld": bool(cld),
                "comorbid_hiv": bool(hiv),
                "comorbid_other": other_comorb.strip(),
                "allergy_drug": bool(allergy_drug),
                "allergy_food": bool(allergy_food),
                "allergy_other": allergy_other.strip(),
            })
            st.success("Saved ✅")
        except Exception as e:
            st.error(f"Save failed: {e}")
            st.info("If DB is missing columns, open DB Setup Help and run SQL.")
            st.stop()


def adherence_page():
    st.header("Adherence + DOTS")
    fid = st.session_state["facility_id"]

    dfp = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    if dfp.empty:
        st.warning("Add a patient first.")
        return

    labels = (dfp["patient_id"].astype(str) + " — " + dfp["full_name"].astype(str)).tolist()
    chosen = st.selectbox("Select patient", labels)
    patient_id = chosen.split(" — ")[0].strip()

    st.subheader("DOTS daily tick (today)")
    today = dt.date.today().isoformat()
    dose_taken = st.checkbox("Dose taken today", True)
    note = st.text_input("Note (optional)", "")

    if st.button("Save DOTS tick", type="primary"):
        db_upsert("dots_daily", {
            "facility_id": fid,
            "patient_id": patient_id,
            "date": today,
            "dose_taken": bool(dose_taken),
            "note": note.strip(),
            "created_at": now_iso(),
        }, on_conflict="facility_id,patient_id,date")
        st.success("Saved ✅")

    dfd = db_select("dots_daily", filters={"facility_id": fid, "patient_id": patient_id}, order_col="date", desc=False)
    if dfd.empty:
        st.info("No DOTS records yet.")
        return

    dfd["date"] = pd.to_datetime(dfd["date"], errors="coerce")
    dfd = dfd.dropna(subset=["date"]).sort_values("date")

    cutoff7 = pd.Timestamp(dt.date.today() - dt.timedelta(days=6))
    cutoff28 = pd.Timestamp(dt.date.today() - dt.timedelta(days=27))
    w7 = dfd[dfd["date"] >= cutoff7]
    w28 = dfd[dfd["date"] >= cutoff28]
    missed_7 = int((~w7["dose_taken"].astype(bool)).sum()) if not w7.empty else 0
    missed_28 = int((~w28["dose_taken"].astype(bool)).sum()) if not w28.empty else 0

    adh7 = compute_adherence_percent(missed_7, 7)
    adh28 = compute_adherence_percent(missed_28, 28)
    flag = missed_over_25pct(missed_28)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Missed (7d)", missed_7)
    c2.metric("Adherence (7d)", f"{adh7:.1f}%")
    c3.metric("Missed (28d)", missed_28)
    c4.metric("Adherence (28d)", f"{adh28:.1f}%")

    missed_streak = st.selectbox("Longest missed streak (self report)", MISSED_STREAK_OPTIONS)
    completed = st.checkbox("Completed regimen", False)

    level = risk_level(flag, missed_streak, completed)

    if flag:
        st.markdown('<div class="danger"><b>⚠️ Alert:</b> Missed >25% doses in last 28 days → high risk of failure/resistance.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ok"><b>Status:</b> Missed-dose threshold OK.</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="warn"><b>Risk level:</b> {level} &nbsp; | &nbsp; Reminder: 08:00 and 14:00 daily (download from Home)</div>', unsafe_allow_html=True)

    if st.button("Save adherence snapshot", type="primary"):
        db_insert("adherence", {
            "adherence_id": make_code("ADH"),
            "facility_id": fid,
            "patient_id": patient_id,
            "timestamp": now_iso(),
            "missed_7": int(missed_7),
            "missed_28": int(missed_28),
            "missed_streak": missed_streak,
            "completed": bool(completed),
            "adh_7_pct": float(adh7),
            "adh_28_pct": float(adh28),
            "flag_over_25pct": bool(flag),
            "risk_level": level,
            "notes": note.strip(),
        })
        st.success("Saved ✅")

    with st.expander("DOTS table"):
        show = dfd.copy()
        show["date"] = show["date"].dt.date.astype(str)
        st.dataframe(show.sort_values("date", ascending=False), use_container_width=True, hide_index=True)


def reports_page():
    st.header("Reports + Export")
    fid = st.session_state["facility_id"]

    st.subheader("Facility export (your facility only)")
    df_pat = db_select("patients", filters={"facility_id": fid}, order_col="created_at", desc=True)
    df_evt = db_select("events", filters={"facility_id": fid}, order_col="timestamp", desc=True)
    df_dot = db_select("dots_daily", filters={"facility_id": fid}, order_col="date", desc=True)
    df_adh = db_select("adherence", filters={"facility_id": fid}, order_col="timestamp", desc=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.download_button("patients.csv", df_pat.to_csv(index=False).encode("utf-8"), "patients.csv", "text/csv", use_container_width=True)
    c2.download_button("events.csv", df_evt.to_csv(index=False).encode("utf-8"), "events.csv", "text/csv", use_container_width=True)
    c3.download_button("dots_daily.csv", df_dot.to_csv(index=False).encode("utf-8"), "dots_daily.csv", "text/csv", use_container_width=True)
    c4.download_button("adherence.csv", df_adh.to_csv(index=False).encode("utf-8"), "adherence.csv", "text/csv", use_container_width=True)

    st.divider()
    st.subheader("Organizer export (ALL facilities)")
    if not st.session_state.get("organizer_mode"):
        st.info("Organizer export locked. Unlock it on Facility onboarding with organizer master key.")
        return

    if st.button("Generate ALL facilities export", type="primary"):
        all_fac = db_select("facilities")
        all_usr = db_select("users")
        all_pat = db_select("patients")
        all_evt = db_select("events")
        all_dot = db_select("dots_daily")
        all_adh = db_select("adherence")

        st.download_button("ALL_facilities.csv", all_fac.to_csv(index=False).encode("utf-8"), "ALL_facilities.csv", "text/csv")
        st.download_button("ALL_users.csv", all_usr.to_csv(index=False).encode("utf-8"), "ALL_users.csv", "text/csv")
        st.download_button("ALL_patients.csv", all_pat.to_csv(index=False).encode("utf-8"), "ALL_patients.csv", "text/csv")
        st.download_button("ALL_events.csv", all_evt.to_csv(index=False).encode("utf-8"), "ALL_events.csv", "text/csv")
        st.download_button("ALL_dots_daily.csv", all_dot.to_csv(index=False).encode("utf-8"), "ALL_dots_daily.csv", "text/csv")
        st.download_button("ALL_adherence.csv", all_adh.to_csv(index=False).encode("utf-8"), "ALL_adherence.csv", "text/csv")


def sidebar_nav() -> str:
    with st.sidebar:
        st.markdown("### OHIH TB Platform")
        st.write(f"**Facility:** {st.session_state['facility_name']}")
        st.write(f"**User:** {st.session_state['user_name']}")
        st.write(f"**Role:** {st.session_state['user_role']}")
        if st.session_state.get("organizer_mode"):
            st.success("Organizer mode: ON")

        st.markdown("---")
        page = st.radio("Menu", ["Home", "Patients", "Diagnosis", "Adherence + DOTS", "Reports", "DB Setup Help"])
        st.markdown("---")
        if st.button("Logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            ss_init()
            st.rerun()
        return page


# =========================
# ENTRY
# =========================
if not supabase_ready():
    st.error("Missing Supabase credentials. Add SUPABASE_URL, SUPABASE_ANON_KEY, APP_PEPPER, ORGANIZER_MASTER_KEY in Streamlit secrets.")
    st.stop()

if not st.session_state["logged_in"]:
    onboarding()
else:
    page = sidebar_nav()
    if page == "Home":
        home_page()
    elif page == "Patients":
        patients_page()
    elif page == "Diagnosis":
        diagnosis_page()
    elif page == "Adherence + DOTS":
        adherence_page()
    elif page == "Reports":
        reports_page()
    else:
        db_setup_page()
