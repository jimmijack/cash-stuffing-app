import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
import plotly.express as px

# --- 1. KONFIGURATION & CSS ---
st.set_page_config(page_title="Cash Stuffing Planer", layout="wide", page_icon="💶")

# Custom CSS
st.markdown("""
    <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
        div[data-testid="stMetric"] {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 10px;
            border-radius: 8px;
            color: var(--text-color);
        }
        thead tr th:first-child {display:none}
        tbody th {display:none}
        
        /* Tab Styling */
        div[data-baseweb="tab-list"] { gap: 5px; }
        button[data-baseweb="tab"] {
            font-size: 18px !important; 
            font-weight: 600 !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            border-radius: 5px 5px 0 0 !important;
            padding: 10px 20px !important;
            background-color: var(--secondary-background-color);
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            border-bottom: 2px solid #ff4b4b !important;
            background-color: var(--background-color);
        }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "/data/budget.db"

DE_MONTHS = {1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni", 7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"}
DEFAULT_CATEGORIES = ["Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", "Sonstiges", "Fixkosten", "Kleidung", "Geschenke", "Notgroschen"]
PRIO_OPTIONS = ["A - Hoch", "B - Mittel", "C - Niedrig", "Standard"]
CYCLE_OPTIONS = ["Monatlich", "Vierteljährlich", "Halbjährlich", "Jährlich"]

# --- 2. HELPER ---
def format_euro(val):
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

def get_db_connection():
    return sqlite3.connect(DB_FILE)

def execute_db(query, params=()):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(query, params)
        conn.commit()
        res = True
    except Exception as e:
        res = False
    conn.close()
    return res

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, description TEXT, amount REAL, type TEXT, budget_month TEXT, is_online INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, priority TEXT DEFAULT 'Standard', target_amount REAL DEFAULT 0.0, due_date TEXT, notes TEXT, is_fixed INTEGER DEFAULT 0, default_budget REAL DEFAULT 0.0, is_cashless INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS loans (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, start_date TEXT, total_amount REAL, interest_amount REAL DEFAULT 0.0, term_months INTEGER, monthly_payment REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, amount REAL, cycle TEXT, category TEXT, start_date TEXT, notice_period TEXT)''')
    
    # NEU: Tabelle für Scheine-Historie
    c.execute('''CREATE TABLE IF NOT EXISTS denominations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        total_amount REAL,
        c200 INTEGER DEFAULT 0,
        c100 INTEGER DEFAULT 0,
        c50 INTEGER DEFAULT 0,
        c20 INTEGER DEFAULT 0,
        c10 INTEGER DEFAULT 0,
        c5 INTEGER DEFAULT 0
    )''')

    # Migrations
    try: c.execute("SELECT default_budget FROM categories LIMIT 1")
    except: c.execute("ALTER TABLE categories ADD COLUMN default_budget REAL DEFAULT 0.0")
    try: c.execute("SELECT interest_amount FROM loans LIMIT 1")
    except: c.execute("ALTER TABLE loans ADD COLUMN interest_amount REAL DEFAULT 0.0")
    try: c.execute("SELECT is_cashless FROM categories LIMIT 1")
    except: c.execute("ALTER TABLE categories ADD COLUMN is_cashless INTEGER DEFAULT 0")

    c.execute("SELECT count(*) FROM categories")
    if c.fetchone()[0] == 0:
        for cat in DEFAULT_CATEGORIES:
            is_fix = 1 if cat in ["Miete", "Fixkosten"] else 0
            c.execute("INSERT OR IGNORE INTO categories (name, priority, is_fixed) VALUES (?, ?, ?)", (cat, "Standard", is_fix))
    conn.commit()
    conn.close()

def get_data(query, params=()):
    conn = get_db_connection()
    try: df = pd.read_sql_query(query, conn, params=params)
    except: df = pd.DataFrame()
    conn.close()
    return df

# --- Wrapper ---
def add_category_to_db(new_cat, prio, is_fixed=0, is_cashless=0):
    return execute_db("INSERT INTO categories (name, priority, is_fixed, is_cashless) VALUES (?, ?, ?, ?)", (new_cat, prio, is_fixed, is_cashless))

def delete_category_from_db(cat_to_del):
    return execute_db("DELETE FROM categories WHERE name = ?", (cat_to_del,))

def load_main_data():
    df = get_data("SELECT * FROM transactions")
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['budget_month'] = df['budget_month'].fillna(df['date'].dt.strftime('%Y-%m'))
        df['is_online'] = df['is_online'].fillna(0).astype(int)
        df['Analyse_Monat'] = df.apply(lambda r: f"{DE_MONTHS[int(r['budget_month'].split('-')[1])]} {r['budget_month'].split('-')[0]}" if r['type']=='SOLL' and '-' in str(r['budget_month']) else f"{DE_MONTHS[r['date'].month]} {r['date'].year}", axis=1)
        df['sort_key_month'] = df.apply(lambda r: int(r['budget_month'].replace('-','')) if r['type']=='SOLL' and '-' in str(r['budget_month']) else r['date'].year*100+r['date'].month, axis=1)
        df['Jahr'] = df['date'].dt.year
        df['Quartal'] = "Q" + df['date'].dt.quarter.astype(str) + " " + df['Jahr'].astype(str)
    return df

def get_categories_full():
    df = get_data("SELECT * FROM categories ORDER BY name ASC")
    cols = ['is_fixed', 'is_cashless', 'default_budget']
    for col in cols:
        if col not in df.columns: df[col] = 0
        
    df['is_fixed'] = df['is_fixed'].fillna(0).astype(int)
    df['is_cashless'] = df['is_cashless'].fillna(0).astype(int)
    return df

try: init_db()
except: pass

# --- UI ---
df = load_main_data()
cat_df = get_categories_full()
current_categories = cat_df['name'].tolist() if not cat_df.empty else []

st.title("💶 Cash Stuffing Planer")

with st.sidebar:
    st.markdown("### 🧭 Navigation")
    # Tools Tab entfernt, ist jetzt Haupt-Tab
    sb_mode = st.segmented_control("Menü", ["📝 Neu", "💰 Verteiler", "💸 Transfer", "🏦 Bank", "📉 Kredite", "🔄 Abos"], selection_mode="single", default="📝 Neu")
    st.divider()

    # 1. NEU
    if sb_mode == "📝 Neu":
        st.subheader("Buchung")
        with st.form("entry_form", clear_on_submit=True):
            col_d, col_t = st.columns([1,1])
            date_input = col_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
            type_input = col_t.selectbox("Typ", ["IST (Ausgabe)", "SOLL (Budget)"])
            budget_target = None
            if "SOLL" in type_input:
                today = date.today()
                nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
                opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
                bm_sel = st.radio("Ziel", [opt1, opt2], horizontal=True)
                budget_target = today.strftime("%Y-%m") if bm_sel == opt1 else nm.strftime("%Y-%m")
            
            if current_categories:
                cat_input = st.selectbox("Kategorie", current_categories)
                cat_row = cat_df[cat_df['name'] == cat_input].iloc[0]
                is_fixed_cat = cat_row['is_fixed'] == 1
                is_cashless_cat = cat_row['is_cashless'] == 1
                
                amt_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
                desc_input = st.text_input("Text")
                
                is_online = False
                if "IST" in type_input:
                    default_chk = True if (is_fixed_cat or is_cashless_cat) else False
                    is_online = st.checkbox("💳 Online / Karte?", value=default_chk) 
                
                if st.form_submit_button("Speichern", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                               (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
                    st.toast("✅ Gespeichert!")
                    st.rerun()
            else: st.error("Keine Kategorien.")

    # 2. VERTEILER (NEU MIT STÜCKELUNG)
    elif sb_mode == "💰 Verteiler":
        st.subheader("Budget Verteiler & Stückelung")
        bulk_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        today = date.today()
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
        bulk_target_sel = st.radio("Ziel", [opt1, opt2], horizontal=True)
        bulk_month = today.strftime("%Y-%m") if bulk_target_sel == opt1 else nm.strftime("%Y-%m")

        # Session State Initialisierung
        if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
            # Wir bauen eine Matrix auf
            temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
            temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag']
            
            # Neue Spalten für Scheine
            temp['50er'] = 0
            temp['20er'] = 0
            temp['10er'] = 0
            temp['5er'] = 0
            
            # Initialer Restbetrag ist das Default Budget
            # Wenn Fix oder Cashless, dann bleibt Rest_Betrag voll.
            # Wenn Cash, dann sollte man es eigentlich auf Scheine aufteilen. 
            # Wir lassen es erstmal in Rest, User verteilt es dann.
            
            st.session_state.bulk_df = temp

        st.caption("Verteile deine Scheine pro Kategorie. Fixkosten/Online kommen in 'Rest'.")
        
        # Berechnung der Summe pro Zeile
        calc_df = st.session_state.bulk_df.copy()
        calc_df['Summe'] = (calc_df['50er']*50) + (calc_df['20er']*20) + (calc_df['10er']*10) + (calc_df['5er']*5) + calc_df['Rest_Betrag']
        
        # Data Editor Konfiguration
        edited = st.data_editor(
            calc_df,
            column_config={
                "Kategorie": st.column_config.TextColumn(disabled=True),
                "is_fixed": st.column_config.CheckboxColumn("Fix", disabled=True, width="small"),
                "is_cashless": st.column_config.CheckboxColumn("Karte", disabled=True, width="small"),
                "50er": st.column_config.NumberColumn("50€", min_value=0, step=1, width="small"),
                "20er": st.column_config.NumberColumn("20€", min_value=0, step=1, width="small"),
                "10er": st.column_config.NumberColumn("10€", min_value=0, step=1, width="small"),
                "5er": st.column_config.NumberColumn("5€", min_value=0, step=1, width="small"),
                "Rest_Betrag": st.column_config.NumberColumn("Rest / Digital €", min_value=0.0, format="%.2f", step=1.0),
                "Summe": st.column_config.NumberColumn("Gesamt €", format="%.2f", disabled=True),
                # Versteckte Spalten
                "default_budget": None
            },
            column_order=["Kategorie", "is_fixed", "is_cashless", "50er", "20er", "10er", "5er", "Rest_Betrag", "Summe"],
            hide_index=True, use_container_width=True, height=500
        )
        
        # Sync back to session state to keep edits alive on interaction
        st.session_state.bulk_df = edited[['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag', '50er', '20er', '10er', '5er']]

        total_budget = edited["Summe"].sum()
        
        # Zusammenfassung Scheine (Nur für nicht-fixe, nicht-cashless Kategorien, oder einfach alles was in den Spalten steht)
        # Wir zählen einfach stur was in den Spalten steht, das ist am ehrlichsten.
        sum_50 = edited['50er'].sum()
        sum_20 = edited['20er'].sum()
        sum_10 = edited['10er'].sum()
        sum_5 = edited['5er'].sum()
        
        cash_total = (sum_50*50) + (sum_20*20) + (sum_10*10) + (sum_5*5)
        digital_total = edited['Rest_Betrag'].sum() # Hier sind Fixkosten und krumme Beträge drin
        
        st.divider()
        st.markdown(f"**Gesamt-Budget: {format_euro(total_budget)}**")
        
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.info(f"🏦 **Vom Konto / Digital:** {format_euro(digital_total)}")
        with col_res2:
            st.success(f"💵 **Am Automaten abheben:** {format_euro(cash_total)}")
            st.markdown(f"""
            *   **{sum_50}x** 50 €
            *   **{sum_20}x** 20 €
            *   **{sum_10}x** 10 €
            *   **{sum_5}x** 5 €
            """)
        
        if st.button("Budgets buchen & Stückelung speichern", type="primary", use_container_width=True):
            if total_budget > 0:
                c = 0
                for _, row in edited.iterrows():
                    row_sum = (row['50er']*50) + (row['20er']*20) + (row['10er']*10) + (row['5er']*5) + row['Rest_Betrag']
                    if row_sum > 0:
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (bulk_date, row["Kategorie"], "Verteiler", row_sum, "SOLL", bulk_month, 0))
                        c += 1
                
                # Speichere die Stückelung in die Historie (denominations Tabelle)
                if cash_total > 0:
                    execute_db("INSERT INTO denominations (date, total_amount, c50, c20, c10, c5) VALUES (?,?,?,?,?,?)",
                               (bulk_date.strftime("%Y-%m-%d"), cash_total, int(sum_50), int(sum_20), int(sum_10), int(sum_5)))
                
                st.success(f"✅ {c} Budgets gebucht und Stückelung gespeichert!")
                
                # Reset
                temp_reset = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
                temp_reset.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag']
                temp_reset['50er']=0; temp_reset['20er']=0; temp_reset['10er']=0; temp_reset['5er']=0
                st.session_state.bulk_df = temp_reset
                st.rerun()
            else:
                st.warning("Summe ist 0.")

    # 3. TRANSFER
    elif sb_mode == "💸 Transfer":
        st.subheader("Umbuchung")
        with st.form("trf"):
            t_date = st.date_input("Datum", date.today())
            c_from = st.selectbox("Von", current_categories)
            c_to = st.selectbox("Nach", current_categories, index=1 if len(current_categories)>1 else 0)
            t_amt = st.number_input("Betrag", min_value=0.01, format="%.2f")
            if st.form_submit_button("Buchen", use_container_width=True):
                if c_from != c_to:
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_from, f"Zu {c_to}", -t_amt, "SOLL", t_date.strftime("%Y-%m")))
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_to, f"Von {c_from}", t_amt, "SOLL", t_date.strftime("%Y-%m")))
                    st.success("✅ Erledigt")
                    st.rerun()
                else: st.error("Identisch.")

    # 4. BANK
    elif sb_mode == "🏦 Bank":
        st.subheader("Back to Bank")
        conn = get_db_connection()
        q = """SELECT SUM(t.amount) FROM transactions t LEFT JOIN categories c ON t.category = c.name 
               WHERE t.type='IST' AND t.is_online=1 AND (c.is_fixed=0 OR c.is_fixed IS NULL) AND (c.is_cashless=0 OR c.is_cashless IS NULL)"""
        online = pd.read_sql_query(q, conn).iloc[0,0] or 0.0
        dep = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='BANK_DEPOSIT'", conn).iloc[0,0] or 0.0
        conn.close()
        bal = online - dep
        st.metric("Im Umschlag", format_euro(bal), help="Bargeld aus Umschlägen für Online-Käufe.")
        
        if bal > 0:
            with st.form("bf"):
                d_amt = st.number_input("Betrag einzahlen", value=float(bal), max_value=float(bal), format="%.2f")
                if st.form_submit_button("Einzahlen", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (date.today(), "Back to Bank", "Einzahlung", d_amt, "BANK_DEPOSIT", date.today().strftime("%Y-%m")))
                    st.success("✅")
                    st.rerun()
        else: st.success("Leer.")

    # 5. KREDITE (ADD)
    elif sb_mode == "📉 Kredite":
        st.subheader("Kredit hinzufügen")
        with st.form("loan_add"):
            l_name = st.text_input("Name (z.B. PayPal)")
            l_sum = st.number_input("Kreditsumme (€)", min_value=0.0, step=50.0)
            l_zins_sum = st.number_input("Zinsen Gesamt (€)", min_value=0.0, step=10.0)
            l_rate = st.number_input("Rate (€/Monat)", min_value=0.0, step=10.0)
            l_start = st.date_input("Datum der 1. Rate", date.today())
            l_term = st.number_input("Laufzeit (Monate)", min_value=1, value=12)
            
            if st.form_submit_button("Kredit anlegen", use_container_width=True):
                execute_db("INSERT INTO loans (name, start_date, total_amount, interest_amount, term_months, monthly_payment) VALUES (?,?,?,?,?,?)",
                           (l_name, l_start, l_sum, l_zins_sum, l_term, l_rate))
                st.success("Gespeichert!")
                st.rerun()

    # 6. ABOS (NEU)
    elif sb_mode == "🔄 Abos":
        st.subheader("Abo hinzufügen")
        with st.form("sub_add"):
            s_name = st.text_input("Name (z.B. Netflix)")
            s_cost = st.number_input("Kosten (€)", min_value=0.0, format="%.2f")
            s_cycle = st.selectbox("Turnus", CYCLE_OPTIONS)
            s_cat = st.selectbox("Kategorie (optional)", [""] + current_categories, index=0)
            s_start = st.date_input("Startdatum (Optional)", date.today())
            
            if st.form_submit_button("Abo anlegen", use_container_width=True):
                execute_db("INSERT INTO subscriptions (name, amount, cycle, category, start_date) VALUES (?,?,?,?,?)",
                           (s_name, s_cost, s_cycle, s_cat, s_start))
                st.success("Abo gespeichert!")
                st.rerun()

    # --- SETTINGS ---
    st.markdown("---")
    with st.expander("⚙️ Verwaltung & Backup"):
        
        st.caption("Neue Kategorie")
        with st.form("add_cat_form", clear_on_submit=True):
            c_n, c_p = st.columns([2,1])
            new_name = c_n.text_input("Name", placeholder="Neue Kat.")
            new_prio = c_p.selectbox("Prio", PRIO_OPTIONS)
            
            c_fix, c_cashless = st.columns(2)
            new_fix = c_fix.checkbox("Ist Fixkosten?")
            new_cashless = c_cashless.checkbox("Variabel aber bargeldlos?")
            
            if st.form_submit_button("Hinzufügen"):
                if new_name:
                    if add_category_to_db(new_name, new_prio, 1 if new_fix else 0, 1 if new_cashless else 0):
                        st.success(f"{new_name} angelegt!")
                        if "bulk_df" in st.session_state: del st.session_state.bulk_df
                        st.rerun()
                    else: st.error("Existiert bereits.")
                else: st.warning("Name fehlt.")
        
        st.divider()
        st.caption("Kategorie bearbeiten")
        edit_cat = st.selectbox("Auswahl", current_categories)
        if edit_cat:
            row = cat_df[cat_df['name'] == edit_cat].iloc[0]
            with st.form("edit_cat_form"):
                try: p_idx = PRIO_OPTIONS.index(row['priority'])
                except: p_idx = 3
                ep = st.selectbox("Prio", PRIO_OPTIONS, index=p_idx)
                
                c_e_fix, c_e_cl = st.columns(2)
                ef = c_e_fix.checkbox("Fixkosten?", value=(row['is_fixed']==1))
                ecl = c_e_cl.checkbox("Variabel Bargeldlos?", value=(row['is_cashless']==1))
                
                ed = st.number_input("Standard Budget (€)", value=float(row.get('default_budget', 0.0)), step=10.0)
                
                c_save, c_del = st.columns(2)
                saved = c_save.form_submit_button("Speichern")
                deleted = c_del.form_submit_button("Löschen", type="primary")
                
                if saved:
                    execute_db("UPDATE categories SET priority=?, is_fixed=?, is_cashless=?, default_budget=? WHERE name=?", (ep, 1 if ef else 0, 1 if ecl else 0, ed, edit_cat))
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.success("Gespeichert!")
                    st.rerun()
                if deleted:
                    delete_category_from_db(edit_cat)
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.success("Gelöscht!")
                    st.rerun()
        
        st.divider()
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Backup (.csv)", csv, "budget_backup.csv", "text/csv")
        
        st.divider()
        st.error("Gefahrenzone")
        if st.checkbox("Reset freischalten"):
            if st.button("🧹 Nur Buchungen löschen", type="primary"):
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM sqlite_sequence WHERE name='transactions'")
                st.rerun()
            if st.button("💥 Alles löschen", type="primary"):
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM categories"); execute_db("DELETE FROM loans"); execute_db("DELETE FROM subscriptions"); execute_db("DELETE FROM sqlite_sequence")
                st.rerun()

# --- MAIN TABS ---
if df.empty and not current_categories:
    # 9 Tabs
    t1, t2, t3, t8, t4, t5, t6, t9, t7 = st.tabs(["📊 Übersicht", "🎯 Sparziele", "📉 Kredite", "🔄 Abos", "📈 Analyse", "⚖️ Vergleich", "📝 Daten", "🧮 Scheine", "📖 Anleitung"])
    st.info("Start: Lege in der Sidebar Kategorien an.")
else:
    # 9 Tabs
    tab_dash, tab_sf, tab_ana, tab_subs, tab_loans, tab_comp, tab_data, tab_money, tab_help = st.tabs(["📊 Übersicht", "🎯 Sparziele", "📈 Analyse", "🔄 Abos", "📉 Kredite", "⚖️ Vergleich", "📝 Daten", "🧮 Scheine", "📖 Hilfe"])

    # T1 Dashboard
    with tab_dash:
        # FIXKOSTEN RADAR
        st.markdown("##### 📌 Fixkosten & Belastungen (Monat)")
        
        l_df = get_data("SELECT * FROM loans")
        loan_monthly = 0.0
        if not l_df.empty:
            l_df['start_date'] = pd.to_datetime(l_df['start_date'])
            today = datetime.datetime.now()
            def is_active(row):
                end_date = row['start_date'] + relativedelta(months=row['term_months'])
                return today <= end_date
            active_loans = l_df[l_df.apply(is_active, axis=1)]
            loan_monthly = active_loans['monthly_payment'].sum()

        s_df = get_data("SELECT * FROM subscriptions")
        sub_monthly = 0.0
        if not s_df.empty:
            def get_m_cost(r):
                a = r['amount']
                if r['cycle'] == "Jährlich": return a/12
                if r['cycle'] == "Halbjährlich": return a/6
                if r['cycle'] == "Vierteljährlich": return a/3
                return a
            sub_monthly = s_df.apply(get_m_cost, axis=1).sum()

        cf1, cf2, cf3 = st.columns(3)
        cf1.metric("Ø Abos & Verträge", format_euro(sub_monthly))
        cf2.metric("Kreditraten", format_euro(loan_monthly))
        cf3.metric("Fixlast Gesamt", format_euro(sub_monthly + loan_monthly), delta="Muss verdient werden", delta_color="off")
        
        st.divider()
        
        if df.empty: st.info("Keine Daten für Budget.")
        else:
            col_m, col_cat = st.columns([1, 3])
            m_opts = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            if not m_opts.empty:
                sel_m = col_m.selectbox("Zeitraum", m_opts['Analyse_Monat'].unique(), label_visibility="collapsed")
                sel_c = col_cat.multiselect("Filter", current_categories, default=current_categories, label_visibility="collapsed", placeholder="Alle Kategorien")
                
                key = m_opts[m_opts['Analyse_Monat'] == sel_m]['sort_key_month'].iloc[0]
                d_c = df[(df['sort_key_month'] == key) & (df['type'].isin(['SOLL','IST']))].copy()
                d_p = df[(df['sort_key_month'] < key) & (df['type'].isin(['SOLL','IST']))].copy()
                
                pg = d_p.groupby(['category','type'])['amount'].sum().unstack(fill_value=0)
                if 'SOLL' not in pg: pg['SOLL']=0; 
                if 'IST' not in pg: pg['IST']=0
                co = pg['SOLL'] - pg['IST']
                
                cg = d_c.groupby(['category','type'])['amount'].sum().unstack(fill_value=0)
                if 'SOLL' not in cg: cg['SOLL']=0; 
                if 'IST' not in cg: cg['IST']=0
                
                ov = pd.DataFrame({'Übertrag': co, 'Budget': cg['SOLL'], 'Ausgaben': cg['IST']}).fillna(0)
                if sel_c: ov = ov[ov.index.isin(sel_c)]
                else: ov = ov[ov.index.isin([])]
                
                ov['Gesamt'] = ov['Übertrag'] + ov['Budget']
                ov['Rest'] = ov['Gesamt'] - ov['Ausgaben']
                ov['Quote'] = (ov['Ausgaben']/ov['Gesamt']).fillna(0)
                
                ov = ov.merge(cat_df.set_index('name')[['priority','is_fixed', 'is_cashless']], left_index=True, right_index=True, how='left')
                ov['priority'] = ov['priority'].fillna('Standard')
                
                s = ov.sum(numeric_only=True)
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Verfügbar", format_euro(s['Gesamt']), delta=f"Übertrag: {format_euro(s['Übertrag'])}")
                k2.metric("Ausgaben", format_euro(s['Ausgaben']), delta=f"{s['Quote']*100:.1f}%", delta_color="inverse")
                k3.metric("Rest", format_euro(s['Rest']), delta_color="normal")
                
                # B2B Calculation for Dashboard
                b2b = d_c[(d_c['is_online']==1) & (d_c['category'].isin(sel_c))].merge(cat_df, left_on='category', right_on='name')
                b2b_s = b2b[(b2b['is_fixed']==0) & (b2b['is_cashless']==0)]['amount'].sum()
                
                if b2b_s > 0: k4.warning(f"Bank: {format_euro(b2b_s)}", icon="💳")
                else: k4.success("Bank: 0 €", icon="✅")
                
                st.markdown("### 📋 Budget Übersicht")
                ov = ov.sort_values(by=['priority', 'Rest'], ascending=[True, False])
                cfg = {
                    "Quote": st.column_config.ProgressColumn("Status", format="%.0f%%", min_value=0, max_value=1), 
                    "Übertrag": st.column_config.NumberColumn(format="%.2f €"), 
                    "Budget": st.column_config.NumberColumn(format="%.2f €"), 
                    "Gesamt": st.column_config.NumberColumn(format="%.2f €"), 
                    "Ausgaben": st.column_config.NumberColumn(format="%.2f €"), 
                    "Rest": st.column_config.NumberColumn(format="%.2f €"), 
                    "is_fixed": st.column_config.CheckboxColumn("Fix", width="small"),
                    "is_cashless": st.column_config.CheckboxColumn("Karte", width="small")
                }
                st.dataframe(ov[['priority','is_fixed', 'is_cashless', 'Übertrag','Budget','Gesamt','Ausgaben','Rest','Quote']], use_container_width=True, column_config=cfg, height=500)
                
                with st.expander("🔎 Details"):
                    ts = d_c[d_c['category'].isin(ov.index)].copy()
                    ts['M'] = ts['is_online'].apply(lambda x: "💳" if x==1 else "💵")
                    st.dataframe(ts[['date','category','description','amount','type','M']].sort_values(by='date', ascending=False), use_container_width=True, column_config={"amount": st.column_config.NumberColumn(format="%.2f €"), "date": st.column_config.DateColumn(format="DD.MM.YYYY")}, hide_index=True)

    # T2 Sinking
    with tab_sf:
        st.subheader("🎯 Sparziele")
        sfc = pd.Series(dtype=float)
        if not df.empty:
            sfc = df[df['type'].isin(['SOLL','IST'])].groupby('category')['amount'].apply(lambda x: x[df['type']=='SOLL'].sum() - x[df['type']=='IST'].sum())
        
        sfd = cat_df.set_index('name').copy()
        sfd['Aktuell'] = sfc
        sfd['Aktuell'] = sfd['Aktuell'].fillna(0.0)
        sfd['due_date'] = pd.to_datetime(sfd['due_date'], errors='coerce')
        
        def cr(row):
            t = row['target_amount']
            if t <= 0: return 0.0, "-"
            c = row['Aktuell']
            if c >= t: return 0.0, "✅"
            d = row['due_date']
            if pd.isnull(d): return 0.0, "?"
            now = datetime.datetime.now()
            if d <= now: return (t-c), "❗"
            dif = relativedelta(d, now)
            m = dif.years*12 + dif.months
            if m < 1: m = 1
            return (t-c)/m, f"{m} M"

        re = sfd.apply(cr, axis=1, result_type='expand')
        sfd['Rate'] = re[0]
        sfd['Info'] = re[1]
        sfd['Progress'] = (sfd['Aktuell']/sfd['target_amount']).fillna(0).clip(0,1)
        
        # Live Rate
        total_monthly_need = sfd[sfd['target_amount'] > 0]['Rate'].sum()
        prio_sums = sfd[sfd['target_amount'] > 0].groupby('priority')['Rate'].sum()
        sum_a = prio_sums.get('A - Hoch', 0.0)
        sum_b = prio_sums.get('B - Mittel', 0.0)
        sum_c = prio_sums.get('C - Niedrig', 0.0)
        
        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("Notwendige Gesamtrate", format_euro(total_monthly_need), help="Summe aller monatlichen Sparraten um Ziele fristgerecht zu erreichen.")
        kc2.metric("Prio A (Hoch)", format_euro(sum_a))
        kc3.metric("Prio B (Mittel)", format_euro(sum_b))
        kc4.metric("Prio C (Niedrig)", format_euro(sum_c))
        st.divider()
        
        for p in PRIO_OPTIONS:
            g = sfd[sfd['priority'] == p].reset_index()
            if not g.empty:
                st.markdown(f"**{p}**")
                ek = f"sf_{p}"
                col_cfg = {
                    "name": st.column_config.TextColumn("Kategorie", disabled=True),
                    "Aktuell": st.column_config.NumberColumn("Ist-Stand", format="%.2f €", disabled=True),
                    "target_amount": st.column_config.NumberColumn("Zielbetrag (€)", format="%.2f €", required=True),
                    "due_date": st.column_config.DateColumn("Fällig am", format="DD.MM.YYYY"),
                    "Progress": st.column_config.ProgressColumn("Fortschritt", format="%.0f%%"),
                    "Rate": st.column_config.NumberColumn("Sparrate/Monat", format="%.2f €", disabled=True),
                    "Info": st.column_config.TextColumn("Zeitraum", disabled=True),
                    "notes": st.column_config.TextColumn("Notiz")
                }
                ed = st.data_editor(g, key=ek, use_container_width=True, hide_index=True, column_order=["name","Aktuell","target_amount","due_date","Progress","Rate","Info","notes"], column_config=col_cfg)
                
                if st.session_state[ek]["edited_rows"]:
                    for i, ch in st.session_state[ek]["edited_rows"].items():
                        cn = g.iloc[i]['name']
                        nt = ch.get("target_amount", g.iloc[i]['target_amount'])
                        nd = ch.get("due_date", g.iloc[i]['due_date'])
                        nn = ch.get("notes", g.iloc[i]['notes'])
                        
                        if pd.isnull(nd): nd = None
                        elif isinstance(nd, (datetime.date, datetime.datetime, pd.Timestamp)): nd = nd.strftime("%Y-%m-%d")
                        
                        execute_db("UPDATE categories SET target_amount=?, due_date=?, notes=? WHERE name=?", (nt, nd, nn, cn))
                    st.rerun()

    # T3 Analysis
    with tab_ana:
        st.subheader("Analyse")
        if df.empty: st.info("Leer.")
        else:
            di = df[df['type']=='IST'].copy()
            if di.empty: st.info("Keine Ausgaben.")
            else:
                c1, c2 = st.columns(2)
                with c1: st.plotly_chart(px.pie(di, values='amount', names='category', title='Kategorien'), use_container_width=True)
                with c2: st.plotly_chart(px.bar(di.groupby(['budget_month','category'])['amount'].sum().reset_index(), x='budget_month', y='amount', color='category', title='Trend'), use_container_width=True)

    # T4 Abos
    with tab_subs:
        st.subheader("🔄 Abos & Verträge")
        subs_df = get_data("SELECT * FROM subscriptions")
        if subs_df.empty: st.info("Keine Abos vorhanden. Füge welche über die Sidebar hinzu.")
        else:
            subs_df['start_date'] = pd.to_datetime(subs_df['start_date'])
            def calc_monthly_cost(row):
                amt = row['amount']
                if row['cycle'] == "Jährlich": return amt / 12
                if row['cycle'] == "Vierteljährlich": return amt / 3
                if row['cycle'] == "Halbjährlich": return amt / 6
                return amt
            subs_df['Monatlich'] = subs_df.apply(calc_monthly_cost, axis=1)
            c1, c2 = st.columns(2)
            c1.metric("Monatliche Belastung (Ø)", format_euro(subs_df['Monatlich'].sum()))
            c2.metric("Jährliche Gesamtkosten", format_euro(subs_df['Monatlich'].sum() * 12))
            
            sub_cfg = {
                "id": st.column_config.NumberColumn(disabled=True), 
                "name": st.column_config.TextColumn("Anbieter"), 
                "amount": st.column_config.NumberColumn("Kosten (€)", format="%.2f €"), 
                "cycle": st.column_config.SelectboxColumn("Turnus", options=CYCLE_OPTIONS), 
                "category": st.column_config.SelectboxColumn("Kategorie", options=[""]+current_categories), 
                "start_date": st.column_config.DateColumn("Startdatum"), 
                "notice_period": st.column_config.TextColumn("Kündigungsfrist"), 
                "Monatlich": st.column_config.NumberColumn("Ø Monat", format="%.2f €", disabled=True)
            }
            edited_subs = st.data_editor(subs_df, key="sub_editor", hide_index=True, use_container_width=True, column_config=sub_cfg, column_order=["name", "amount", "cycle", "Monatlich", "category", "start_date", "notice_period"], num_rows="dynamic")
            
            if st.session_state["sub_editor"]:
                chg = st.session_state["sub_editor"]
                for i in chg["deleted_rows"]: execute_db("DELETE FROM subscriptions WHERE id=?", (int(subs_df.iloc[i]['id']),))
                for i, v in chg["edited_rows"].items():
                    sid = subs_df.iloc[i]['id']
                    for k, val in v.items():
                        if k == 'start_date':
                            if pd.isnull(val): val = None
                            elif isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                        execute_db(f"UPDATE subscriptions SET {k}=? WHERE id=?", (val, int(sid)))
                if chg["added_rows"]:
                    for row in chg["added_rows"]:
                        execute_db("INSERT INTO subscriptions (name, amount, cycle, category, start_date, notice_period) VALUES (?,?,?,?,?,?)", (row.get("name","Neu"), row.get("amount",0), row.get("cycle","Monatlich"), row.get("category","Fixkosten"), row.get("start_date",date.today()), row.get("notice_period","")))
                if chg["deleted_rows"] or chg["edited_rows"] or chg["added_rows"]: st.rerun()

    # T5 Loans
    with tab_loans:
        st.subheader("📉 Kredit Übersicht")
        loans_df = get_data("SELECT * FROM loans")
        
        if loans_df.empty:
            st.info("Keine Kredite angelegt. Nutze die Sidebar.")
        else:
            loans_df['start_date'] = pd.to_datetime(loans_df['start_date'])
            
            def calc_loan(row):
                total_liability = row['total_amount'] + row.get('interest_amount', 0.0)
                today = date.today()
                start = row['start_date'].date()
                if today < start: months_passed = 0
                else: months_passed = (today.year - start.year) * 12 + (today.month - start.month) + 1 
                
                if months_passed > row['term_months']: months_passed = row['term_months']
                
                paid_so_far = months_passed * row['monthly_payment']
                if paid_so_far > total_liability: paid_so_far = total_liability
                
                remaining = total_liability - paid_so_far
                progress = paid_so_far / total_liability if total_liability > 0 else 0
                end_date = row['start_date'] + relativedelta(months=row['term_months'])
                status = "✅ Bezahlt" if remaining <= 0 else f"{int(row['term_months'] - months_passed)} Raten offen"
                return status, progress, remaining, end_date, total_liability

            res = loans_df.apply(calc_loan, axis=1, result_type='expand')
            loans_df['Status'] = res[0]; loans_df['Progress'] = res[1]; loans_df['Rest'] = res[2]; loans_df['Ende'] = res[3]; loans_df['Gesamt'] = res[4]
            
            c1, c2 = st.columns(2)
            c1.metric("Monatliche Belastung", format_euro(loans_df[loans_df['Rest'] > 0]['monthly_payment'].sum()))
            c2.metric("Gesamtschulden (Rest)", format_euro(loans_df['Rest'].sum()))
            
            loan_cfg = {
                "id": st.column_config.NumberColumn(disabled=True), 
                "name": st.column_config.TextColumn("Kredit"), 
                "start_date": st.column_config.DateColumn("Startdatum"), 
                "total_amount": st.column_config.NumberColumn("Nettokredit", format="%.2f €"), 
                "interest_amount": st.column_config.NumberColumn("Zinsen gesamt (€)", format="%.2f €"), 
                "Gesamt": st.column_config.NumberColumn("Bruttoschuld", format="%.2f €", disabled=True), 
                "term_months": st.column_config.NumberColumn("Laufzeit (Monate)"), 
                "monthly_payment": st.column_config.NumberColumn("Rate", format="%.2f €"), 
                "Progress": st.column_config.ProgressColumn("Status", format="%.0f%%"), 
                "Rest": st.column_config.NumberColumn("Restschuld", format="%.2f €", disabled=True), 
                "Ende": st.column_config.DateColumn(format="DD.MM.YYYY", disabled=True), 
                "Status": st.column_config.TextColumn(disabled=True)
            }
            
            edited_loans = st.data_editor(
                loans_df, 
                key="loan_editor",
                hide_index=True,
                use_container_width=True,
                column_config=loan_cfg,
                column_order=["name", "monthly_payment", "Rest", "Progress", "Gesamt", "interest_amount", "start_date", "term_months", "Ende"],
                num_rows="dynamic"
            )
            
            if st.session_state["loan_editor"]:
                chg = st.session_state["loan_editor"]
                for i in chg["deleted_rows"]: 
                    execute_db("DELETE FROM loans WHERE id=?", (int(loans_df.iloc[i]['id']),))
                for i, v in chg["edited_rows"].items():
                    lid = loans_df.iloc[i]['id']
                    for k, val in v.items():
                        if k == 'start_date':
                            if pd.isnull(val): val = None
                            elif isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                        execute_db(f"UPDATE loans SET {k}=? WHERE id=?", (val, int(lid)))
                if chg["added_rows"]:
                    for row in chg["added_rows"]:
                        execute_db("INSERT INTO loans (name, start_date, total_amount, interest_amount, term_months, monthly_payment) VALUES (?,?,?,?,?,?)", (row.get("name","Neu"), row.get("start_date",date.today()), row.get("total_amount",0), row.get("interest_amount",0), row.get("term_months",12), row.get("monthly_payment",0)))
                if chg["deleted_rows"] or chg["edited_rows"] or chg["added_rows"]: st.rerun()

    # T6 Compare
    with tab_comp:
        st.subheader("Vergleich")
        if df.empty: st.info("Leer.")
        else:
            ps = sorted(df['Analyse_Monat'].unique(), reverse=True)
            if len(ps)>1:
                c1,c2 = st.columns(2)
                p1 = c1.selectbox("Basis", ps, index=0)
                p2 = c2.selectbox("Vgl", ps, index=1)
                def gs(p):
                    k = m_opts[m_opts['Analyse_Monat']==p]['sort_key_month'].iloc[0]
                    return df[(df['sort_key_month']==k)&(df['type']=='IST')].groupby('category')['amount'].sum()
                cp = pd.DataFrame({'Basis': gs(p1), 'Vgl': gs(p2)}).fillna(0)
                cp['Diff'] = cp['Basis'] - cp['Vgl']
                st.dataframe(cp.style.format("{:.2f} €").background_gradient(cmap="RdYlGn_r", subset=['Diff']), use_container_width=True)
            else: st.info("Zu wenig Daten.")

    # T7 Editor
    with tab_data:
        st.subheader("Editor")
        de = get_data("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        if not de.empty: de['date'] = pd.to_datetime(de['date'])
        cf = {
            "id": st.column_config.NumberColumn(disabled=True), 
            "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"), 
            "category": st.column_config.SelectboxColumn("Kategorie", options=current_categories + ["Back to Bank"]), 
            "type": st.column_config.SelectboxColumn("Typ", options=["IST", "SOLL", "BANK_DEPOSIT"]), 
            "amount": st.column_config.NumberColumn("Betrag", format="%.2f €"), 
            "is_online": st.column_config.CheckboxColumn("Online?"),
            "budget_month": st.column_config.TextColumn("Budget-Monat"),
            "description": st.column_config.TextColumn("Beschreibung")
        }
        er = st.data_editor(de, hide_index=True, use_container_width=True, column_config=cf, key="me", num_rows="dynamic")
        
        if st.session_state["me"]:
            ch = st.session_state["me"]
            for i in ch["deleted_rows"]: execute_db("DELETE FROM transactions WHERE id=?", (int(de.iloc[i]['id']),))
            for i, v in ch["edited_rows"].items():
                rid = de.iloc[i]['id']
                for k, val in v.items():
                    if k == 'date':
                        if pd.isnull(val): val = None
                        elif isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                    if k=='is_online': val=1 if val else 0
                    execute_db(f"UPDATE transactions SET {k}=? WHERE id=?", (val, int(rid)))
            for r in ch["added_rows"]:
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                           (r.get('date', date.today()), r.get('category', 'Sonstiges'), r.get('description', ''), r.get('amount', 0), r.get('type', 'IST'), r.get('budget_month', date.today().strftime('%Y-%m')), 1 if r.get('is_online') else 0))
            if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

    # T8 Money
    with tab_money:
        st.subheader("🧮 Scheine Rechner & Historie")
        denoms = get_data("SELECT * FROM denominations ORDER BY date DESC")
        if not denoms.empty:
            denoms['date'] = pd.to_datetime(denoms['date'])
            # Chart
            fig = px.bar(denoms, x='date', y=['c50','c20','c10','c5'], title="Historie Scheine")
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("##### Letzte Abhebungen")
            st.dataframe(denoms, hide_index=True, use_container_width=True)
        else:
            st.info("Noch keine Stückelung gespeichert (via Verteiler).")

    # T9 Anleitung
    with tab_help:
        st.subheader("📖 Anleitung & Workflow")
        
        with st.expander("1️⃣ Einrichtung & Kategorien", expanded=True):
            st.markdown("""
            1. **⚙️ Verwaltung**: Erstelle deine Kategorien.
            2. **Fixkosten**: Haken bei "Ist Fixkosten", wenn es vom Konto abgeht (Miete).
            3. **Bargeldlos**: Haken bei "Variabel aber bargeldlos", wenn es ein variables Budget ist, das du aber meistens online zahlst (z.B. Drogerie Online). Das System sagt dir dann beim Verteilen, dass du dafür kein Bargeld abheben musst.
            """)
            
        with st.expander("2️⃣ Monatsanfang (Geld verteilen)"):
            st.markdown("""
            1. **💰 Verteiler**: Wähle den Monat.
            2. Trage in die Spalten (50er, 20er...) ein, wie viele Scheine du für den Umschlag brauchst.
            3. Bei Fixkosten oder Online-Budgets trage den Betrag einfach bei "Rest/Digital" ein.
            4. "Budgets buchen" erstellt die SOLL-Einträge und speichert deine Schein-Liste.
            """)
            
        with st.expander("3️⃣ Hybrid-System & Ausgaben"):
            st.markdown("""
            1. **Ausgaben erfassen**: Wenn du einen Umschlag (z.B. Freizeit) online benutzt (z.B. Kinokarten online), setze den Haken **💳 Online**.
            2. **🏦 Bank (Back to Bank)**: Das System merkt, dass du Bargeld im Umschlag hast, das eigentlich weg ist. Es sagt dir: "Nimm X Euro aus dem Umschlag und zahl es ein".
            """)
