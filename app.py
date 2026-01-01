import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
import plotly.express as px

# --- 1. KONFIGURATION & CSS (MOBILE OPTIMIERT) ---
st.set_page_config(page_title="Cash Stuffing", layout="wide", page_icon="💶", initial_sidebar_state="collapsed")

# Custom CSS - Mobile Friendly
st.markdown("""
    <style>
        /* Mobile Padding reduzieren */
        .block-container {
            padding-top: 1rem !important; 
            padding-bottom: 3rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        
        /* Metrik-Boxen */
        div[data-testid="stMetric"] {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 8px;
            border-radius: 8px;
            color: var(--text-color);
        }
        
        /* Navigation oben größer machen für Touch */
        div[data-baseweb="segmented-control"] button {
            font-size: 16px !important;
            padding-top: 8px !important;
            padding-bottom: 8px !important;
        }

        /* Tabellen Header (Index verstecken) */
        thead tr th:first-child {display:none}
        tbody th {display:none}
        
        /* Buttons mobilfreundlicher */
        button {
            min-height: 45px !important;
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
    c.execute('''CREATE TABLE IF NOT EXISTS denominations (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, total_amount REAL, c200 INTEGER DEFAULT 0, c100 INTEGER DEFAULT 0, c50 INTEGER DEFAULT 0, c20 INTEGER DEFAULT 0, c10 INTEGER DEFAULT 0, c5 INTEGER DEFAULT 0)''')

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

# --- UI START ---
df = load_main_data()
cat_df = get_categories_full()
current_categories = cat_df['name'].tolist() if not cat_df.empty else []

# --- TOP NAVIGATION (MOBILE FRIENDLY) ---
# Menüpunkte gekürzt für mobile Anzeige
menu_options = ["📊 Übersicht", "📝 Neu", "💰 Verteiler", "🎯 Ziele", "📈 Kredit/Abo", "🏦 Bank", "⚙️ Daten"]
selected_view = st.segmented_control("", menu_options, default="📊 Übersicht", label_visibility="collapsed")

# --- SIDEBAR (Nur noch Settings) ---
with st.sidebar:
    st.header("Einstellungen")
    
    with st.expander("⚙️ Kategorien verwalten", expanded=False):
        st.caption("Neue Kategorie")
        with st.form("add_cat_form", clear_on_submit=True):
            new_name = st.text_input("Name", placeholder="z.B. Urlaub")
            new_prio = st.selectbox("Prio", PRIO_OPTIONS)
            c_fix, c_cl = st.columns(2)
            new_fix = c_fix.checkbox("Fixkosten?")
            new_cl = c_cl.checkbox("Karte?")
            if st.form_submit_button("Hinzufügen"):
                if new_name:
                    add_category_to_db(new_name, new_prio, 1 if new_fix else 0, 1 if new_cl else 0)
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.rerun()
        
        st.divider()
        edit_cat = st.selectbox("Bearbeiten", [""] + current_categories)
        if edit_cat:
            row = cat_df[cat_df['name'] == edit_cat].iloc[0]
            with st.form("edit_cat_form"):
                ep = st.selectbox("Prio", PRIO_OPTIONS, index=PRIO_OPTIONS.index(row['priority']) if row['priority'] in PRIO_OPTIONS else 3)
                c_ef, c_ecl = st.columns(2)
                ef = c_ef.checkbox("Fixkosten?", value=(row['is_fixed']==1))
                ecl = c_ecl.checkbox("Karte?", value=(row['is_cashless']==1))
                ed = st.number_input("Std. Budget", value=float(row.get('default_budget', 0.0)))
                
                c_s, c_d = st.columns(2)
                if c_s.form_submit_button("Speichern"):
                    execute_db("UPDATE categories SET priority=?, is_fixed=?, is_cashless=?, default_budget=? WHERE name=?", (ep, 1 if ef else 0, 1 if ecl else 0, ed, edit_cat))
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.rerun()
                if c_d.form_submit_button("Löschen", type="primary"):
                    delete_category_from_db(edit_cat)
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.rerun()

    with st.expander("🚨 Reset / Backup"):
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Backup laden", csv, "budget.csv", "text/csv")
        if st.checkbox("Reset freigeben"):
            if st.button("Buchungen löschen", type="primary"):
                execute_db("DELETE FROM transactions")
                st.rerun()

# --- MAIN CONTENT ---

if not current_categories:
    st.info("Bitte öffne das Menü oben links (>) um Kategorien anzulegen.")

# 1. DASHBOARD
elif selected_view == "📊 Übersicht":
    # FIXKOSTEN RADAR (Kompakt)
    l_df = get_data("SELECT * FROM loans")
    s_df = get_data("SELECT * FROM subscriptions")
    
    loan_m = 0.0
    if not l_df.empty:
        l_df['start_date'] = pd.to_datetime(l_df['start_date'])
        now = datetime.datetime.now()
        act_l = l_df[l_df.apply(lambda r: now <= (r['start_date'] + relativedelta(months=r['term_months'])), axis=1)]
        loan_m = act_l['monthly_payment'].sum()

    sub_m = 0.0
    if not s_df.empty:
        sub_m = s_df.apply(lambda r: r['amount']/12 if r['cycle']=="Jährlich" else (r['amount']/3 if r['cycle']=="Vierteljährlich" else (r['amount']/6 if r['cycle']=="Halbjährlich" else r['amount'])), axis=1).sum()

    st.markdown(f"**Fixlast:** {format_euro(loan_m + sub_m)} (Abos: {format_euro(sub_m)} | Kredite: {format_euro(loan_m)})")
    st.divider()

    if df.empty: st.info("Keine Buchungen.")
    else:
        # Filter oben
        col_m, col_f = st.columns([1,1])
        m_opts = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
        if not m_opts.empty:
            sel_m = col_m.selectbox("Monat", m_opts['Analyse_Monat'].unique(), label_visibility="collapsed")
            sel_c = col_f.multiselect("Kat.", current_categories, label_visibility="collapsed", placeholder="Filter")
            
            key = m_opts[m_opts['Analyse_Monat'] == sel_m]['sort_key_month'].iloc[0]
            d_c = df[(df['sort_key_month'] == key) & (df['type'].isin(['SOLL','IST']))].copy()
            d_p = df[(df['sort_key_month'] < key) & (df['type'].isin(['SOLL','IST']))].copy()
            
            # Calc
            pg = d_p.groupby(['category','type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in pg: pg['SOLL']=0; 
            if 'IST' not in pg: pg['IST']=0
            
            cg = d_c.groupby(['category','type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in cg: cg['SOLL']=0; 
            if 'IST' not in cg: cg['IST']=0
            
            ov = pd.DataFrame({'Übertrag': pg['SOLL']-pg['IST'], 'Budget': cg['SOLL'], 'Ausgaben': cg['IST']}).fillna(0)
            if sel_c: ov = ov[ov.index.isin(sel_c)]
            
            ov['Rest'] = (ov['Übertrag'] + ov['Budget']) - ov['Ausgaben']
            ov['Quote'] = (ov['Ausgaben'] / (ov['Übertrag'] + ov['Budget'])).fillna(0)
            
            # Merge Metadata
            ov = ov.merge(cat_df.set_index('name')[['priority','is_fixed','is_cashless']], left_index=True, right_index=True, how='left')
            ov = ov.sort_values(by=['priority', 'Rest'], ascending=[True, False])
            
            # KPIs
            sums = ov.sum(numeric_only=True)
            k1, k2, k3 = st.columns(3)
            k1.metric("Verfügbar", format_euro(sums['Übertrag']+sums['Budget']))
            k2.metric("Ausgaben", format_euro(sums['Ausgaben']))
            k3.metric("Rest", format_euro(sums['Rest']), delta_color="normal")
            
            # Tabelle Mobil Optimiert (Weniger Spalten)
            cfg = {
                "Quote": st.column_config.ProgressColumn(" %", format="%.0f%%", width="small"),
                "Rest": st.column_config.NumberColumn("Rest", format="%.0f €", width="small"), # Ohne Cents für Platz
                "Ausgaben": st.column_config.NumberColumn("Ist", format="%.0f", width="small"),
                "Budget": st.column_config.NumberColumn("Neu", format="%.0f", width="small"),
            }
            st.dataframe(ov[['Rest', 'Quote', 'Ausgaben', 'Budget']], use_container_width=True, column_config=cfg)
            
            with st.expander("Buchungen"):
                ts = d_c.copy()
                if sel_c: ts = ts[ts['category'].isin(sel_c)]
                ts['Art'] = ts['is_online'].apply(lambda x: "💳" if x==1 else "💵")
                st.dataframe(ts[['date','category','amount','Art']].sort_values('date', ascending=False), hide_index=True, use_container_width=True, column_config={"date": st.column_config.DateColumn("Datum", format="DD.MM"), "amount": st.column_config.NumberColumn("€", format="%.2f")})

# 2. NEU (EINGABE)
elif selected_view == "📝 Neu":
    st.subheader("Neuer Eintrag")
    with st.form("entry_form", clear_on_submit=True):
        c_d, c_t = st.columns([1,1])
        date_input = c_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
        type_input = c_t.selectbox("Typ", ["IST (Ausgabe)", "SOLL (Budget)"], label_visibility="collapsed")
        
        budget_target = None
        if "SOLL" in type_input:
            today = date.today()
            nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            bm_sel = st.radio("Ziel", [f"{DE_MONTHS[today.month]}", f"{DE_MONTHS[nm.month]}"], horizontal=True)
            budget_target = today.strftime("%Y-%m") if str(DE_MONTHS[today.month]) in bm_sel else nm.strftime("%Y-%m")
        
        cat_input = st.selectbox("Kategorie", current_categories)
        
        c_a, c_on = st.columns([2,1])
        amt_input = c_a.number_input("Betrag (€)", min_value=0.0, format="%.2f")
        
        # Auto-Check Online
        cat_row = cat_df[cat_df['name'] == cat_input].iloc[0]
        def_online = True if (cat_row['is_fixed'] or cat_row['is_cashless']) else False
        is_online = False
        if "IST" in type_input:
            is_online = c_on.checkbox("Karte?", value=def_online)
            
        desc_input = st.text_input("Notiz (Optional)")
        
        if st.form_submit_button("💾 Speichern", use_container_width=True, type="primary"):
            execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                       (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
            st.toast("Gespeichert!")
            st.rerun()

# 3. VERTEILER
elif selected_view == "💰 Verteiler":
    st.subheader("Budget & Scheine")
    
    col_d, col_check = st.columns([1,1])
    bulk_date = col_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
    
    today = date.today()
    nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    bulk_target_sel = st.radio("Ziel-Monat", [f"{DE_MONTHS[today.month]}", f"{DE_MONTHS[nm.month]}"], horizontal=True)
    bulk_month = today.strftime("%Y-%m") if str(DE_MONTHS[today.month]) in bulk_target_sel else nm.strftime("%Y-%m")

    if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
        temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
        temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest']
        temp['50'] = 0; temp['20'] = 0; temp['10'] = 0; temp['5'] = 0; temp['Notiz'] = ""
        st.session_state.bulk_df = temp

    # Calc Sums live
    calc_df = st.session_state.bulk_df.copy()
    calc_df['Summe'] = (calc_df['50']*50) + (calc_df['20']*20) + (calc_df['10']*10) + (calc_df['5']*5) + calc_df['Rest']
    
    # Kompakte Spaltennamen für Mobile
    edited = st.data_editor(
        calc_df,
        column_config={
            "Kategorie": st.column_config.TextColumn(disabled=True),
            "is_fixed": st.column_config.CheckboxColumn("Fix", disabled=True, width="small"),
            "is_cashless": st.column_config.CheckboxColumn("Krt", disabled=True, width="small"), # Krt = Karte
            "50": st.column_config.NumberColumn("50", min_value=0, step=1, width="small"),
            "20": st.column_config.NumberColumn("20", min_value=0, step=1, width="small"),
            "10": st.column_config.NumberColumn("10", min_value=0, step=1, width="small"),
            "5": st.column_config.NumberColumn("5", min_value=0, step=1, width="small"),
            "Rest": st.column_config.NumberColumn("Rest/Dig.", min_value=0.0, format="%.2f"),
            "Summe": st.column_config.NumberColumn("∑", format="%.2f", disabled=True, width="small"),
            "default_budget": None
        },
        column_order=["Kategorie", "50", "20", "10", "5", "Rest", "Summe", "Notiz"],
        hide_index=True, use_container_width=True, height=500
    )
    
    st.session_state.bulk_df = edited[['Kategorie', 'is_fixed', 'is_cashless', 'Rest', '50', '20', '10', '5', 'Notiz']]
    
    total = edited["Summe"].sum()
    # Cash Total: Nur Scheine zählen
    cash_total = (edited['50'].sum()*50) + (edited['20'].sum()*20) + (edited['10'].sum()*10) + (edited['5'].sum()*5)
    
    c1, c2 = st.columns(2)
    c1.metric("Gesamt", format_euro(total))
    c2.metric("Bar abheben", format_euro(cash_total))
    
    if st.button(f"Buchen ({format_euro(total)})", type="primary", use_container_width=True):
        if total > 0:
            c = 0
            for _, row in edited.iterrows():
                row_sum = (row['50']*50) + (row['20']*20) + (row['10']*10) + (row['5']*5) + row['Rest']
                if row_sum > 0:
                    desc = "Verteiler" + (f": {row['Notiz']}" if row['Notiz'] else "")
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                               (bulk_date, row["Kategorie"], desc, row_sum, "SOLL", bulk_month, 0))
                    c += 1
            if cash_total > 0:
                execute_db("INSERT INTO denominations (date, total_amount, c200, c100, c50, c20, c10, c5) VALUES (?,?,?,0,0,?,?,?,?)",
                           (bulk_date.strftime("%Y-%m-%d"), cash_total, 0, int(edited['50'].sum()), int(edited['20'].sum()), int(edited['10'].sum()), int(edited['5'].sum())))
            
            st.success(f"✅ {c} Budgets gebucht!")
            # Reset
            temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
            temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Rest']
            temp['50'] = 0; temp['20'] = 0; temp['10'] = 0; temp['5'] = 0; temp['Notiz'] = ""
            st.session_state.bulk_df = temp
            st.rerun()
        else: st.warning("0 €")

# 4. ZIELE
elif selected_view == "🎯 Ziele":
    st.subheader("Sparziele")
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
    
    total_rate = sfd[sfd['target_amount']>0]['Rate'].sum()
    st.metric("Monatliche Sparrate gesamt", format_euro(total_rate))
    
    for p in PRIO_OPTIONS:
        g = sfd[sfd['priority'] == p].reset_index()
        if not g.empty:
            st.caption(f"{p}")
            ek = f"sf_{p}"
            # Weniger Spalten für Mobile
            col_cfg = {
                "name": st.column_config.TextColumn("Topf", disabled=True),
                "Aktuell": st.column_config.NumberColumn("Ist", format="%.0f €", disabled=True, width="small"),
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

# 5. KREDIT / ABO
elif selected_view == "📈 Kredit/Abo":
    t_sub, t_loan = st.tabs(["Abos", "Kredite"])
    
    with t_sub:
        subs_df = get_data("SELECT * FROM subscriptions")
        if not subs_df.empty:
            subs_df['start_date'] = pd.to_datetime(subs_df['start_date'])
            def cmc(r):
                a = r['amount']
                if r['cycle'] == "Jährlich": return a/12
                if r['cycle'] == "Vierteljährlich": return a/3
                if r['cycle'] == "Halbjährlich": return a/6
                return a
            subs_df['M'] = subs_df.apply(cmc, axis=1)
            st.metric("Ø Monatlich", format_euro(subs_df['M'].sum()))
            
            sc = {"id": st.column_config.NumberColumn(disabled=True), "name": "Abo", "amount": st.column_config.NumberColumn("€", format="%.2f"), "cycle": st.column_config.SelectboxColumn("Turnus", options=CYCLE_OPTIONS), "start_date": st.column_config.DateColumn("Start"), "notice_period": "Frist"}
            es = st.data_editor(subs_df, key="se", hide_index=True, use_container_width=True, column_config=sc, column_order=["name","amount","cycle","start_date"], num_rows="dynamic")
            
            if st.session_state["se"]:
                ch = st.session_state["se"]
                for i in ch["deleted_rows"]: execute_db("DELETE FROM subscriptions WHERE id=?", (int(subs_df.iloc[i]['id']),))
                for i, v in ch["edited_rows"].items():
                    sid = subs_df.iloc[i]['id']
                    for k, val in v.items():
                        if k == 'start_date' and isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                        execute_db(f"UPDATE subscriptions SET {k}=? WHERE id=?", (val, int(sid)))
                for r in ch["added_rows"]:
                    execute_db("INSERT INTO subscriptions (name, amount, cycle, category, start_date) VALUES (?,?,?,?,?)", (r.get("name","Neu"), r.get("amount",0), r.get("cycle","Monatlich"), "Fixkosten", date.today()))
                if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()
        else:
            st.info("Keine Abos. (Nutze Tabelle unten zum Hinzufügen)")
            # Add Dummy for easy add
            if st.button("Erstes Abo anlegen"):
                execute_db("INSERT INTO subscriptions (name, amount, cycle) VALUES ('Neu', 0, 'Monatlich')")
                st.rerun()

    with t_loan:
        loans_df = get_data("SELECT * FROM loans")
        if not loans_df.empty:
            loans_df['start_date'] = pd.to_datetime(loans_df['start_date'])
            def cl(row):
                tl = row['total_amount'] + row.get('interest_amount', 0.0)
                today = date.today()
                s = row['start_date'].date()
                mp = (today.year - s.year) * 12 + (today.month - s.month) + 1 if today >= s else 0
                if mp > row['term_months']: mp = row['term_months']
                paid = mp * row['monthly_payment']
                if paid > tl: paid = tl
                rem = tl - paid
                prog = paid / tl if tl > 0 else 0
                return prog, rem

            res = loans_df.apply(cl, axis=1, result_type='expand')
            loans_df['Prog'] = res[0]; loans_df['Rest'] = res[1]
            
            st.metric("Restschuld", format_euro(loans_df['Rest'].sum()))
            
            lc = {"id": st.column_config.NumberColumn(disabled=True), "name": "Kredit", "total_amount": st.column_config.NumberColumn("Summe", format="%.0f €"), "monthly_payment": st.column_config.NumberColumn("Rate", format="%.0f €"), "Prog": st.column_config.ProgressColumn("%"), "Rest": st.column_config.NumberColumn("Rest", format="%.0f €", disabled=True)}
            el = st.data_editor(loans_df, key="le", hide_index=True, use_container_width=True, column_config=lc, column_order=["name","monthly_payment","Rest","Prog"], num_rows="dynamic")
            
            if st.session_state["le"]:
                ch = st.session_state["le"]
                for i in ch["deleted_rows"]: execute_db("DELETE FROM loans WHERE id=?", (int(loans_df.iloc[i]['id']),))
                for i, v in ch["edited_rows"].items():
                    lid = loans_df.iloc[i]['id']
                    for k, val in v.items():
                        execute_db(f"UPDATE loans SET {k}=? WHERE id=?", (val, int(lid)))
                for r in ch["added_rows"]:
                    execute_db("INSERT INTO loans (name, start_date, total_amount, term_months, monthly_payment) VALUES (?,?,?,?,?)", (r.get("name","Neu"), date.today(), 0, 12, 0))
                if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()
        else:
            if st.button("Ersten Kredit anlegen"):
                execute_db("INSERT INTO loans (name, start_date, total_amount, term_months, monthly_payment) VALUES ('Neu', ?, 0, 12, 0)", (date.today(),))
                st.rerun()

# 6. BANK
elif selected_view == "🏦 Bank":
    st.subheader("Back to Bank")
    conn = get_db_connection()
    # Nur Cashless-Transaktionen von NICHT-Cashless-Kategorien
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
    else:
        st.success("Alles erledigt.")

# 7. TRANSFER / DATA
elif selected_view == "💸 Transfer":
    st.subheader("Umbuchung")
    with st.form("trf"):
        c_from = st.selectbox("Von", current_categories)
        c_to = st.selectbox("Nach", current_categories, index=1 if len(current_categories)>1 else 0)
        t_amt = st.number_input("Betrag", min_value=0.01, format="%.2f")
        if st.form_submit_button("Buchen", use_container_width=True):
            if c_from != c_to:
                d = date.today()
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (d, c_from, f"Zu {c_to}", -t_amt, "SOLL", d.strftime("%Y-%m")))
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (d, c_to, f"Von {c_from}", t_amt, "SOLL", d.strftime("%Y-%m")))
                st.success("Erledigt")
            else: st.error("Identisch.")

elif selected_view == "⚙️ Daten":
    st.subheader("Alle Daten")
    de = get_data("SELECT * FROM transactions ORDER BY date DESC, id DESC")
    if not de.empty: de['date'] = pd.to_datetime(de['date'])
    cf = {
        "id": st.column_config.NumberColumn(disabled=True), 
        "date": st.column_config.DateColumn("Datum", format="DD.MM.YY"), 
        "category": st.column_config.SelectboxColumn("Kat.", options=current_categories), 
        "type": st.column_config.SelectboxColumn("Typ", options=["IST", "SOLL", "BANK_DEPOSIT"]), 
        "amount": st.column_config.NumberColumn("€", format="%.2f"), 
        "is_online": st.column_config.CheckboxColumn("Web")
    }
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
        if ch["deleted_rows"] or ch["edited_rows"]: st.rerun()
