import streamlit as st
import pandas as pd
import sqlite3
import datetime
import calendar
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
import plotly.express as px
import numpy as np

# --- 1. KONFIGURATION & CSS ---
st.set_page_config(page_title="Cash Stuffing", layout="wide", page_icon="💶", initial_sidebar_state="collapsed")

# Custom CSS
st.markdown("""
    <style>
        /* Sidebar verstecken */
        [data-testid="stSidebar"] {display: none;}
        
        .block-container {padding-top: 1rem !important; padding-bottom: 3rem !important;}
        
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
        div[data-baseweb="tab-list"] { gap: 5px; overflow-x: auto; white-space: nowrap; }
        button[data-baseweb="tab"] {
            font-size: 16px !important; 
            font-weight: 600 !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            border-radius: 8px 8px 0 0 !important;
            padding: 12px 20px !important;
            background-color: var(--secondary-background-color);
            flex: 1; 
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            border-bottom: 3px solid #ff4b4b !important;
            background-color: var(--background-color);
        }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "/data/budget.db"

DE_MONTHS = {1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni", 7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"}
DEFAULT_CATEGORIES = ["Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", "Sonstiges", "Fixkosten", "Kleidung", "Geschenke", "Notgroschen"]
FIXED_COST_GROUPS = ["Wohnkosten", "Versicherungen", "Abos/Software", "Telefon/Handy", "Mobilität", "Unterhalt", "Kredite", "Sonstiges"]
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
    c.execute('''CREATE TABLE IF NOT EXISTS denominations (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, total_amount REAL, c200 INTEGER DEFAULT 0, c100 INTEGER DEFAULT 0, c50 INTEGER DEFAULT 0, c20 INTEGER DEFAULT 0, c10 INTEGER DEFAULT 0, c5 INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS incomes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, amount REAL, day_of_month INTEGER)''')

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
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])
        
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

# --- UI START ---
df = load_main_data()
cat_df = get_categories_full()
current_categories = cat_df['name'].tolist() if not cat_df.empty else []

st.title("💶 Cash Stuffing Planer")

# --- MAIN TABS ---
if df.empty and not current_categories:
    # 9 Tabs
    t_dash, t_book, t_dist, t_sf, t_subs, t_loan, t_fore, t_ana, t_adm = st.tabs(["📊 Übersicht", "📝 Buchen", "💰 Verteiler", "🎯 Ziele", "🔄 Abos", "📉 Kredite", "🔮 Prognose", "📈 Analyse", "⚙️ Admin"])
    st.info("Start: Lege im Reiter '⚙️ Admin' Kategorien an.")
else:
    # 10 Tabs (Hilfe extra)
    tab_dash, tab_book, tab_dist, tab_sf, tab_subs, tab_loans, tab_forecast, tab_ana, tab_admin, tab_money = st.tabs([
        "📊 Übersicht", "📝 Buchen", "💰 Verteiler", "🎯 Ziele", "🔄 Abos", "📉 Kredite", "🔮 Prognose", "📈 Analyse", "⚙️ Admin", "🧮 Scheine"
    ])

    # 1. DASHBOARD
    with tab_dash:
        # FIXKOSTEN RADAR
        with st.expander("📌 Fixkosten & Belastungen (Monat)", expanded=False):
            l_df = get_data("SELECT * FROM loans")
            loan_monthly = 0.0
            if not l_df.empty:
                l_df['start_date'] = pd.to_datetime(l_df['start_date'], errors='coerce')
                today = date.today()
                def is_active(row):
                    if pd.isnull(row['start_date']): return False
                    end_date = (row['start_date'] + relativedelta(months=int(row['term_months']))).date()
                    return today <= end_date
                
                l_df_clean = l_df.dropna(subset=['start_date']).copy()
                if not l_df_clean.empty:
                    active_loans = l_df_clean[l_df_clean.apply(is_active, axis=1)]
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
            cf1.metric("Ø Abos", format_euro(sub_monthly))
            cf2.metric("Kredite", format_euro(loan_monthly))
            cf3.metric("Fixlast Gesamt", format_euro(sub_monthly + loan_monthly), delta="Muss verdient werden", delta_color="off")
        
        st.divider()
        
        if df.empty: st.info("Keine Daten für Budget. Gehe zu 'Verteiler' oder 'Buchen'.")
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

    # 2. BUCHEN
    with tab_book:
        st.subheader("Buchungscenter")
        st_b1, st_b2, st_b3, st_b4 = st.tabs(["📝 Ausgabe/Einzahlung", "💸 Umbuchung", "🏦 Back to Bank", "🧮 Rechner"])
        
        with st_b1:
            with st.form("entry_form", clear_on_submit=True):
                col_d, col_t = st.columns([1,1])
                date_input = col_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
                type_input = col_t.selectbox("Typ", ["IST (Ausgabe)", "SOLL (Budget)"])
                budget_target = None
                if "SOLL" in type_input:
                    today = date.today()
                    nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
                    opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
                    bm_sel = st.radio("Ziel-Monat", [opt1, opt2], horizontal=True)
                    budget_target = today.strftime("%Y-%m") if bm_sel == opt1 else nm.strftime("%Y-%m")
                
                if current_categories:
                    cat_input = st.selectbox("Kategorie", current_categories)
                    cat_row = cat_df[cat_df['name'] == cat_input].iloc[0]
                    is_fixed_cat = cat_row['is_fixed'] == 1
                    is_cashless_cat = cat_row['is_cashless'] == 1
                    
                    amt_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
                    desc_input = st.text_input("Beschreibung / Notiz")
                    
                    is_online = False
                    if "IST" in type_input:
                        default_chk = True if (is_fixed_cat or is_cashless_cat) else False
                        is_online = st.checkbox("💳 Online / Karte?", value=default_chk)
                    
                    if st.form_submit_button("Speichern", use_container_width=True):
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
                        st.toast("✅ Gespeichert!")
                        st.rerun()
                else: st.error("Bitte erst Kategorien im Admin-Bereich anlegen!")
                
        with st_b2:
            with st.form("trf"):
                t_date = st.date_input("Datum", date.today())
                c_from = st.selectbox("Von (Quelle)", current_categories)
                c_to = st.selectbox("Nach (Ziel)", current_categories, index=1 if len(current_categories)>1 else 0)
                t_amt = st.number_input("Betrag", min_value=0.01, format="%.2f")
                if st.form_submit_button("Umbuchen", use_container_width=True):
                    if c_from != c_to:
                        d_s = t_date.strftime("%Y-%m")
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_from, f"Zu {c_to}", -t_amt, "SOLL", d_s))
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_to, f"Von {c_from}", t_amt, "SOLL", d_s))
                        st.success("✅ Erledigt")
                        st.rerun()
                    else: st.error("Identisch.")
                    
        with st_b3:
            conn = get_db_connection()
            q = """SELECT SUM(t.amount) FROM transactions t LEFT JOIN categories c ON t.category = c.name 
                   WHERE t.type='IST' AND t.is_online=1 AND (c.is_fixed=0 OR c.is_fixed IS NULL) AND (c.is_cashless=0 OR c.is_cashless IS NULL)"""
            online = pd.read_sql_query(q, conn).iloc[0,0] or 0.0
            dep = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='BANK_DEPOSIT'", conn).iloc[0,0] or 0.0
            conn.close()
            bal = online - dep
            st.metric("Im Umschlag (muss zur Bank)", format_euro(bal))
            if bal > 0:
                if st.button("Geld eingezahlt (Reset)", type="primary", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (date.today(), "Back to Bank", "Einzahlung", bal, "BANK_DEPOSIT", date.today().strftime("%Y-%m")))
                    st.toast("Eingezahlt!")
                    st.rerun()
            else: st.success("Leer.")
            
        with st_b4:
            st.subheader("Scheinrechner")
            target_val = st.number_input("Betrag", min_value=0, value=500, step=50)
            notes = [200, 100, 50, 20, 10, 5]
            result = {}
            remainder = target_val
            for n in notes:
                count = int(remainder // n)
                if count > 0:
                    result[n] = count
                    remainder -= count * n
            for n, c in result.items(): st.write(f"**{c}x** {n} €")

    # 3. VERTEILER
    with tab_dist:
        st.subheader("Budget Verteiler")
        bulk_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        today = date.today()
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
        bulk_target_sel = st.radio("Ziel-Monat", [opt1, opt2], horizontal=True)
        bulk_month = today.strftime("%Y-%m") if bulk_target_sel == opt1 else nm.strftime("%Y-%m")

        if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
            temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
            temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag']
            temp['50er'] = 0; temp['20er'] = 0; temp['10er'] = 0; temp['5er'] = 0; temp['Notiz'] = ""
            st.session_state.bulk_df = temp

        calc_df = st.session_state.bulk_df.copy()
        calc_df['Summe'] = (calc_df['50er']*50) + (calc_df['20er']*20) + (calc_df['10er']*10) + (calc_df['5er']*5) + calc_df['Rest_Betrag']
        
        edited = st.data_editor(
            calc_df,
            column_config={
                "Kategorie": st.column_config.TextColumn(disabled=True),
                "is_fixed": st.column_config.CheckboxColumn("Fix", disabled=True, width="small"),
                "is_cashless": st.column_config.CheckboxColumn("Krt", disabled=True, width="small"),
                "50er": st.column_config.NumberColumn("50", min_value=0, step=1, width="small"),
                "20er": st.column_config.NumberColumn("20", min_value=0, step=1, width="small"),
                "10er": st.column_config.NumberColumn("10", min_value=0, step=1, width="small"),
                "5er": st.column_config.NumberColumn("5", min_value=0, step=1, width="small"),
                "Rest_Betrag": st.column_config.NumberColumn("Rest/Dig.", min_value=0.0, format="%.2f"),
                "Summe": st.column_config.NumberColumn("∑", format="%.2f", disabled=True, width="small"),
                "default_budget": None
            },
            column_order=["Kategorie", "50er", "20er", "10er", "5er", "Rest_Betrag", "Summe", "Notiz"],
            hide_index=True, use_container_width=True, height=500
        )
        
        st.session_state.bulk_df = edited[['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag', '50er', '20er', '10er', '5er', 'Notiz']]

        total = edited["Summe"].sum()
        sum_50 = edited['50er'].sum(); sum_20 = edited['20er'].sum()
        sum_10 = edited['10er'].sum(); sum_5 = edited['5er'].sum()
        cash_total = (sum_50*50) + (sum_20*20) + (sum_10*10) + (sum_5*5)
        digital_total = edited['Rest_Betrag'].sum()
        
        st.divider()
        st.markdown(f"**Gesamt: {format_euro(total)}**")
        c1, c2 = st.columns(2)
        c1.info(f"Digital: {format_euro(digital_total)}")
        c2.success(f"Bar: {format_euro(cash_total)}")
        
        if st.button("Buchen", type="primary", use_container_width=True):
            if total > 0:
                c = 0
                for _, row in edited.iterrows():
                    row_sum = (row['50er']*50) + (row['20er']*20) + (row['10er']*10) + (row['5er']*5) + row['Rest_Betrag']
                    if row_sum > 0:
                        desc = "Verteiler" + (f": {row['Notiz']}" if row['Notiz'] else "")
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (bulk_date, row["Kategorie"], desc, row_sum, "SOLL", bulk_month, 0))
                        c += 1
                if cash_total > 0:
                    execute_db("INSERT INTO denominations (date, total_amount, c200, c100, c50, c20, c10, c5) VALUES (?,?,?,0,0,?,?,?,?)",
                               (bulk_date.strftime("%Y-%m-%d"), cash_total, 0, int(sum_50), int(sum_20), int(sum_10), int(sum_5)))
                st.success(f"✅ {c} Budgets gebucht!")
                temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
                temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest_Betrag']
                temp['50er']=0; temp['20er']=0; temp['10er']=0; temp['5er']=0; temp['Notiz']=""
                st.session_state.bulk_df = temp
                st.rerun()
            else: st.warning("Summe ist 0.")

    # 4. ZIELE
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
        
        total_monthly_need = sfd[sfd['target_amount'] > 0]['Rate'].sum()
        prio_sums = sfd[sfd['target_amount'] > 0].groupby('priority')['Rate'].sum()
        sum_a = prio_sums.get('A - Hoch', 0.0)
        sum_b = prio_sums.get('B - Mittel', 0.0)
        
        kc1, kc2, kc3 = st.columns(3)
        kc1.metric("Gesamtrate / Monat", format_euro(total_monthly_need))
        kc2.metric("Prio A", format_euro(sum_a))
        kc3.metric("Prio B", format_euro(sum_b))
        st.divider()
        
        for p in PRIO_OPTIONS:
            g = sfd[sfd['priority'] == p].reset_index()
            if not g.empty:
                st.markdown(f"**{p}**")
                ek = f"sf_{p}"
                col_cfg = {
                    "name": st.column_config.TextColumn("Kategorie", disabled=True),
                    "Aktuell": st.column_config.NumberColumn("Ist-Stand", format="%.0f €", disabled=True, width="small"),
                    "target_amount": st.column_config.NumberColumn("Ziel", format="%.0f €", required=True, width="small"),
                    "due_date": st.column_config.DateColumn("Bis", format="DD.MM.YY", width="small"),
                    "Rate": st.column_config.NumberColumn("Rate", format="%.0f €", disabled=True, width="small"),
                    "notes": st.column_config.TextColumn("Notiz")
                }
                ed = st.data_editor(g, key=ek, use_container_width=True, hide_index=True, column_order=["name","Aktuell","target_amount","due_date","Rate","notes"], column_config=col_cfg)
                
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

    # 5. ABOS (NEU SEPARAT)
    with tab_subs:
        st.subheader("🔄 Abos & Verträge")
        subs_df = get_data("SELECT * FROM subscriptions")
        
        # Oben KPIs
        if not subs_df.empty:
            subs_df['start_date'] = pd.to_datetime(subs_df['start_date'], errors='coerce')
            def calc_monthly_cost(row):
                amt = row['amount']
                if row['cycle'] == "Jährlich": return amt / 12
                if row['cycle'] == "Vierteljährlich": return amt / 3
                if row['cycle'] == "Halbjährlich": return amt / 6
                return amt
            subs_df['Monatlich'] = subs_df.apply(calc_monthly_cost, axis=1)
            c1, c2 = st.columns(2)
            c1.metric("Ø Belastung (Monat)", format_euro(subs_df['Monatlich'].sum()))
            c2.metric("Gesamtkosten (Jahr)", format_euro(subs_df['Monatlich'].sum() * 12))
            st.divider()

        # Liste / Editor
        grp_opts = FIXED_COST_GROUPS
        ed_subs = st.data_editor(
            subs_df,
            key="sub_editor_main",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "id": None,
                "name": st.column_config.TextColumn("Name", required=True),
                "category": st.column_config.SelectboxColumn("Gruppe", options=grp_opts),
                "amount": st.column_config.NumberColumn("Betrag", format="%.2f €", required=True),
                "cycle": st.column_config.SelectboxColumn("Turnus", options=CYCLE_OPTIONS),
                "start_date": st.column_config.DateColumn("Start"),
                "notice_period": st.column_config.TextColumn("Frist"),
                "Monatlich": None # Verstecken
            },
            column_order=["name", "category", "amount", "cycle", "start_date", "notice_period"]
        )
        
        # Save Logic
        if st.session_state.get("sub_editor_main"):
            ch = st.session_state["sub_editor_main"]
            for i in ch["deleted_rows"]: execute_db("DELETE FROM subscriptions WHERE id=?", (int(subs_df.iloc[i]['id']),))
            for i, v in ch["edited_rows"].items():
                sid = subs_df.iloc[i]['id']
                for k, val in v.items():
                    if k == 'start_date':
                         if pd.isnull(val): val = None
                         elif isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                    execute_db(f"UPDATE subscriptions SET {k}=? WHERE id=?", (val, int(sid)))
            for r in ch["added_rows"]:
                execute_db("INSERT INTO subscriptions (name, category, amount, cycle, start_date) VALUES (?,?,?,?,?)", 
                           (r.get("name","Neu"), r.get("category","Sonstiges"), r.get("amount",0), r.get("cycle","Monatlich"), date.today()))
            if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

    # 6. KREDITE
    with tab_loans:
        st.subheader("📉 Kredit Übersicht")
        loans_df = get_data("SELECT * FROM loans")
        
        # --- EINGABE BEREICH FÜR KREDITE ---
        with st.expander("➕ Neuen Kredit anlegen"):
            with st.form("new_loan_form", clear_on_submit=True):
                nl_name = st.text_input("Name")
                nl_sum = st.number_input("Summe (Netto)", min_value=0.0)
                nl_start = st.date_input("Start", date.today())
                nl_months = st.number_input("Laufzeit (M)", min_value=1, value=12)
                st.write("Basis:")
                calc_mode = st.radio("Methode", ["Rate", "Zins %", "Zins €"], horizontal=True)
                nl_val = st.number_input("Wert", min_value=0.0)
                
                if st.form_submit_button("Speichern"):
                    rate = 0.0; int_sum = 0.0
                    if calc_mode == "Rate":
                        rate = nl_val; total_pay = rate * nl_months; int_sum = max(0, total_pay - nl_sum)
                    elif calc_mode == "Zins %":
                        monthly_i = (nl_val / 100) / 12
                        rate = nl_sum * (monthly_i * (1 + monthly_i)**nl_months) / ((1 + monthly_i)**nl_months - 1) if monthly_i > 0 else nl_sum/nl_months
                        int_sum = (rate * nl_months) - nl_sum
                    elif calc_mode == "Zins €":
                        int_sum = nl_val; rate = (nl_sum + int_sum) / nl_months
                        
                    execute_db("INSERT INTO loans (name, start_date, total_amount, interest_amount, term_months, monthly_payment) VALUES (?,?,?,?,?,?)",
                               (nl_name, nl_start, nl_sum, int_sum, nl_months, rate))
                    st.success("OK"); st.rerun()
        # -----------------------------------------------

        if not loans_df.empty:
            loans_df['start_date'] = pd.to_datetime(loans_df['start_date'], errors='coerce')
            def calc_loan(row):
                try:
                    if pd.isnull(row['start_date']): return "Fehler", 0.0, 0.0, date.today(), 0.0
                    total_liability = (row['total_amount'] or 0.0) + (row.get('interest_amount') or 0.0)
                    start = row['start_date'].date() if hasattr(row['start_date'], 'date') else row['start_date']
                    today = date.today()
                    if today < start: months_passed = 0
                    else: months_passed = (today.year - start.year) * 12 + (today.month - start.month) + 1 
                    term = int(row['term_months'] or 12)
                    if months_passed > term: months_passed = term
                    paid_so_far = months_passed * (row['monthly_payment'] or 0.0)
                    if paid_so_far > total_liability: paid_so_far = total_liability
                    remaining = total_liability - paid_so_far
                    progress = paid_so_far / total_liability if total_liability > 0 else 0.0
                    end_date = start + relativedelta(months=term)
                    status = "✅ Bezahlt" if remaining <= 0.01 else f"{int(term - months_passed)} Raten"
                    return status, progress, remaining, end_date, total_liability
                except: return "Error", 0,0, date.today(), 0

            res = loans_df.apply(calc_loan, axis=1, result_type='expand')
            loans_df['Status'] = res[0]; loans_df['Progress'] = res[1]; loans_df['Rest'] = res[2]; loans_df['Ende'] = res[3]; loans_df['Gesamt'] = res[4]
            
            c1, c2 = st.columns(2)
            c1.metric("Monatliche Belastung", format_euro(loans_df[loans_df['Rest'] > 0]['monthly_payment'].sum()))
            c2.metric("Gesamtschulden", format_euro(loans_df['Rest'].sum()))
            
            lc = {"id": None, "name": "Kredit", "start_date": st.column_config.DateColumn("Start"), "total_amount": st.column_config.NumberColumn("Netto", format="%.2f €"), "interest_amount": st.column_config.NumberColumn("Zins", format="%.2f €"), "Gesamt": st.column_config.NumberColumn("Brutto", format="%.2f €", disabled=True), "term_months": st.column_config.NumberColumn("Laufzeit"), "monthly_payment": st.column_config.NumberColumn("Rate", format="%.2f €"), "Progress": st.column_config.ProgressColumn("%"), "Rest": st.column_config.NumberColumn("Rest", format="%.2f €", disabled=True), "Ende": st.column_config.DateColumn(format="DD.MM.YY", disabled=True), "Status": st.column_config.TextColumn(disabled=True)}
            
            el = st.data_editor(loans_df, key="le", hide_index=True, use_container_width=True, column_config=lc, column_order=["name","monthly_payment","Rest","Progress","Gesamt","interest_amount","start_date","term_months"], num_rows="dynamic")
            
            if st.session_state["le"]:
                ch = st.session_state["le"]
                for i in ch["deleted_rows"]: execute_db("DELETE FROM loans WHERE id=?", (int(loans_df.iloc[i]['id']),))
                for i, v in ch["edited_rows"].items():
                    lid = loans_df.iloc[i]['id']
                    for k, val in v.items():
                        if k == 'start_date' and isinstance(val, (datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                        execute_db(f"UPDATE loans SET {k}=? WHERE id=?", (val, int(lid)))
                for r in ch["added_rows"]: execute_db("INSERT INTO loans (name, start_date, total_amount, term_months, monthly_payment) VALUES (?,?,?,?,?)", (r.get("name","Neu"), date.today(), 0, 12, 0))
                if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

    # 7. PROGNOSE (REDUZIERT AUF CHART + Einnahmen)
    with tab_forecast:
        st.subheader("🔮 Liquiditäts-Prognose")
        
        today = date.today()
        inc_df = get_data("SELECT * FROM incomes")
        
        col_inp, col_kpi = st.columns([1,3])
        with col_inp:
            if "forecast_start" not in st.session_state: st.session_state.forecast_start = 1000.0
            start_saldo = st.number_input("Kontostand Heute", value=st.session_state.forecast_start, step=50.0, format="%.2f")
            st.session_state.forecast_start = start_saldo
        
        # Events bauen (Einnahmen + Abos + Kredite)
        events = []
        # Einnahmen
        if not inc_df.empty:
            for _, r in inc_df.iterrows():
                try:
                    evt_date = date(today.year, today.month, int(r['day_of_month']))
                    if evt_date >= today: events.append({"Datum": evt_date, "Text": f"💰 {r['name']}", "Betrag": r['amount']})
                except: pass
        
        # Abos (aus DB)
        subs = get_data("SELECT * FROM subscriptions")
        if not subs.empty:
            subs['start_date'] = pd.to_datetime(subs['start_date'], errors='coerce')
            for _, r in subs.iterrows():
                try: 
                    include = False
                    if r['cycle'] == 'Monatlich': include = True
                    elif r['cycle'] == 'Jährlich' and r['start_date'].month == today.month: include = True
                    if include:
                         d_day = r['start_date'].day
                         evt_date = date(today.year, today.month, d_day)
                         if evt_date >= today: events.append({"Datum": evt_date, "Text": f"📉 {r['name']}", "Betrag": -r['amount']})
                except: pass

        # Kredite (aus DB)
        l_df = get_data("SELECT * FROM loans") # Reload to be safe
        if not l_df.empty:
             l_df['start_date'] = pd.to_datetime(l_df['start_date'], errors='coerce')
             # Re-Calculate Active Loans logic simple here
             for _, r in l_df.iterrows():
                 if pd.notnull(r['start_date']):
                     end_d = (r['start_date'] + relativedelta(months=int(r['term_months']))).date()
                     if today <= end_d:
                         try:
                             d_day = r['start_date'].day
                             evt_date = date(today.year, today.month, d_day)
                             if evt_date >= today: events.append({"Datum": evt_date, "Text": f"📉 {r['name']}", "Betrag": -r['monthly_payment']})
                         except: pass

        events.sort(key=lambda x: x['Datum'])
        
        run_bal = start_saldo
        chart_d = [{"Datum": today, "Saldo": start_saldo, "Info": "Start"}]
        table_d = []
        for e in events:
            run_bal += e['Betrag']
            chart_d.append({"Datum": e['Datum'], "Saldo": run_bal, "Info": e['Text']})
            table_d.append(e)
        
        fig = px.line(pd.DataFrame(chart_d), x="Datum", y="Saldo", markers=True, title=f"Verlauf {DE_MONTHS[today.month]}")
        fig.add_hrect(y0=-100000, y1=0, line_width=0, fillcolor="red", opacity=0.1)
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.markdown("#### 📝 Einnahmen verwalten")
        
        ed_inc = st.data_editor(
            inc_df,
            key="inc_editor",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "id": None,
                "name": st.column_config.TextColumn("Name", required=True),
                "amount": st.column_config.NumberColumn("Betrag (€)", format="%.2f €", required=True),
                "day_of_month": st.column_config.NumberColumn("Tag (1-31)", min_value=1, max_value=31, format="%d.")
            }
        )
        if st.session_state.get("inc_editor"):
            ch = st.session_state["inc_editor"]
            for i in ch["deleted_rows"]: execute_db("DELETE FROM incomes WHERE id=?", (int(inc_df.iloc[i]['id']),))
            for i, v in ch["edited_rows"].items():
                rid = inc_df.iloc[i]['id']
                for k, val in v.items(): execute_db(f"UPDATE incomes SET {k}=? WHERE id=?", (val, int(rid)))
            for r in ch["added_rows"]:
                execute_db("INSERT INTO incomes (name, amount, day_of_month) VALUES (?,?,?)", (r.get("name","Neu"), r.get("amount",0), r.get("day_of_month",1)))
            if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

    # 8. ANALYSE
    with tab_ana:
        st.subheader("Analyse")
        if df.empty: st.info("Leer.")
        else:
            di = df[df['type']=='IST'].copy()
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.pie(di, values='amount', names='category', title='Kategorien'), use_container_width=True)
            with c2: st.plotly_chart(px.bar(di.groupby(['budget_month','category'])['amount'].sum().reset_index(), x='budget_month', y='amount', color='category', title='Trend'), use_container_width=True)

    # 9. ADMIN
    with tab_admin:
        st.subheader("⚙️ Admin & Daten")
        
        with st.expander("Kategorien verwalten", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.caption("Neu / Bearbeiten")
                with st.form("admin_cat"):
                    name = st.text_input("Name (Neu oder bestehend)")
                    prio = st.selectbox("Prio", PRIO_OPTIONS)
                    col_a, col_b = st.columns(2)
                    fix = col_a.checkbox("Fixkosten")
                    csh = col_b.checkbox("Bargeldlos")
                    bdg = st.number_input("Standard Budget", min_value=0.0)
                    
                    c_s, c_d = st.columns(2)
                    s = c_s.form_submit_button("Speichern/Update")
                    d = c_d.form_submit_button("Löschen", type="primary")
                    
                    if s and name:
                        ex = get_data("SELECT * FROM categories WHERE name=?", (name,))
                        if ex.empty:
                            add_category_to_db(name, prio, 1 if fix else 0, 1 if csh else 0)
                            execute_db("UPDATE categories SET default_budget=? WHERE name=?", (bdg, name))
                        else:
                            execute_db("UPDATE categories SET priority=?, is_fixed=?, is_cashless=?, default_budget=? WHERE name=?", (prio, 1 if fix else 0, 1 if csh else 0, bdg, name))
                        if "bulk_df" in st.session_state: del st.session_state.bulk_df
                        st.success("OK")
                        st.rerun()
                    if d and name:
                        delete_category_from_db(name)
                        if "bulk_df" in st.session_state: del st.session_state.bulk_df
                        st.success("Deleted")
                        st.rerun()
            
            with col2:
                st.caption("Liste")
                st.dataframe(cat_df, hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("Rohdaten")
        de = get_data("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        if not de.empty: de['date'] = pd.to_datetime(de['date'], errors='coerce')
        
        cf = {"id": st.column_config.NumberColumn(disabled=True), "date": st.column_config.DateColumn(format="DD.MM.YYYY"), "category": st.column_config.SelectboxColumn(options=current_categories + ["Back to Bank"]), "type": st.column_config.SelectboxColumn(options=["IST", "SOLL", "BANK_DEPOSIT"]), "amount": st.column_config.NumberColumn("€", format="%.2f"), "is_online": st.column_config.CheckboxColumn("Web")}
        er = st.data_editor(de, hide_index=True, use_container_width=True, column_config=cf, key="me", num_rows="dynamic")
        
        if st.session_state["me"]:
            ch = st.session_state["me"]
            for i in ch["deleted_rows"]: execute_db("DELETE FROM transactions WHERE id=?", (int(de.iloc[i]['id']),))
            for i, v in ch["edited_rows"].items():
                rid = de.iloc[i]['id']
                for k, val in v.items():
                    if k == 'date' and isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                    if k=='is_online': val=1 if val else 0
                    execute_db(f"UPDATE transactions SET {k}=? WHERE id=?", (val, int(rid)))
            for r in ch["added_rows"]:
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                           (r.get('date', date.today()), r.get('category', 'Sonstiges'), r.get('description', ''), r.get('amount', 0), r.get('type', 'IST'), r.get('budget_month', date.today().strftime('%Y-%m')), 1 if r.get('is_online') else 0))
            if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

        st.divider()
        if st.checkbox("Gefahrenzone: Reset"):
            if st.button("Alles löschen", type="primary"):
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM categories"); execute_db("DELETE FROM loans"); execute_db("DELETE FROM subscriptions"); execute_db("DELETE FROM sqlite_sequence"); execute_db("DELETE FROM denominations"); execute_db("DELETE FROM incomes")
                st.rerun()
