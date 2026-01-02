import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
import plotly.express as px

# --- 1. KONFIGURATION & CSS (Desktop Standard) ---
st.set_page_config(page_title="Cash Stuffing Planer", layout="wide", page_icon="💶")

# Custom CSS - Nur kosmetische Anpassungen für Boxen, kein Layout-Shift
st.markdown("""
    <style>
        /* Metrik-Boxen stylen */
        div[data-testid="stMetric"] {
            background-color: #f8f9fa;
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 10px;
            border-radius: 8px;
            color: #31333F;
        }
        /* Darkmode Anpassung für Metriken */
        @media (prefers-color-scheme: dark) {
            div[data-testid="stMetric"] {
                background-color: #262730;
                color: #FAFAFA;
            }
        }
        /* Tabellen Index verstecken */
        thead tr th:first-child {display:none}
        tbody th {display:none}
        
        /* Reiter etwas größer */
        button[data-baseweb="tab"] {
            font-size: 16px !important;
            font-weight: 600 !important;
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

    # Migrations (Sicherstellen, dass alle Spalten da sind)
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

# --- SIDEBAR: EINGABEN ---
with st.sidebar:
    st.markdown("### 🧭 Menü")
    # Klassisches Radio Button Menü oder Segmented Control in der Sidebar
    sb_mode = st.radio("Aktion wählen", ["📝 Neuer Eintrag", "💰 Budget Verteiler", "💸 Umbuchung", "🏦 Back to Bank", "🧮 Scheinrechner"], label_visibility="collapsed")
    st.divider()

    # 1. NEU
    if sb_mode == "📝 Neuer Eintrag":
        st.subheader("Buchung erfassen")
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
                    is_online = st.checkbox("💳 Online / Karte?", value=default_chk, help="Geld bleibt im Umschlag, muss zur Bank")
                
                if st.form_submit_button("Speichern", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                               (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
                    st.toast("✅ Gespeichert!")
                    st.rerun()
            else: st.error("Bitte erst Kategorien anlegen!")

    # 2. VERTEILER (Zurück in Sidebar, ohne Stückelung für den Anfang um Platz zu sparen, oder kompakt)
    elif sb_mode == "💰 Budget Verteiler":
        st.subheader("Budget Verteiler")
        bulk_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        today = date.today()
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
        bulk_target_sel = st.radio("Ziel", [opt1, opt2], horizontal=True)
        bulk_month = today.strftime("%Y-%m") if bulk_target_sel == opt1 else nm.strftime("%Y-%m")

        if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
            temp = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].copy()
            temp.columns = ['Kategorie', 'is_fixed', 'is_cashless', 'Betrag']
            st.session_state.bulk_df = temp

        st.caption("Standard-Budgets anpassen:")
        edited = st.data_editor(
            st.session_state.bulk_df,
            column_config={
                "Kategorie": st.column_config.TextColumn(disabled=True),
                "Betrag": st.column_config.NumberColumn(format="%.2f", min_value=0),
                "is_fixed": st.column_config.CheckboxColumn("Fix?", disabled=True, width="small"),
                "is_cashless": st.column_config.CheckboxColumn("Karte?", disabled=True, width="small")
            },
            hide_index=True, use_container_width=True, height=400
        )
        
        total = edited["Betrag"].sum()
        fixed_sum = edited[edited['is_fixed']==1]['Betrag'].sum()
        cashless_sum = edited[(edited['is_fixed']==0) & (edited['is_cashless']==1)]['Betrag'].sum()
        cash_sum = total - fixed_sum - cashless_sum
        
        st.markdown(f"**Gesamt: {format_euro(total)}**")
        st.caption(f"Bar abheben: {format_euro(cash_sum)}")
        
        if st.button("Budgets buchen", type="primary", use_container_width=True):
            if total > 0:
                c = 0
                for _, row in edited.iterrows():
                    if row["Betrag"] > 0:
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (bulk_date, row["Kategorie"], "Verteiler", row["Betrag"], "SOLL", bulk_month, 0))
                        c += 1
                st.success(f"✅ {c} Budgets gebucht!")
                st.session_state.bulk_df = cat_df[['name', 'is_fixed', 'is_cashless', 'default_budget']].rename(columns={'name':'Kategorie', 'default_budget':'Betrag'})
                st.rerun()
            else: st.warning("Summe ist 0.")

    # 3. TRANSFER
    elif sb_mode == "💸 Umbuchung":
        st.subheader("Umbuchung")
        with st.form("trf"):
            t_date = st.date_input("Datum", date.today())
            c_from = st.selectbox("Von (Quelle)", current_categories)
            c_to = st.selectbox("Nach (Ziel)", current_categories, index=1 if len(current_categories)>1 else 0)
            t_amt = st.number_input("Betrag", min_value=0.01, format="%.2f")
            if st.form_submit_button("Buchen", use_container_width=True):
                if c_from != c_to:
                    d_s = t_date.strftime("%Y-%m")
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_from, f"Zu {c_to}", -t_amt, "SOLL", d_s))
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (t_date, c_to, f"Von {c_from}", t_amt, "SOLL", d_s))
                    st.success("✅ Erledigt")
                    st.rerun()
                else: st.error("Identisch.")

    # 4. BANK
    elif sb_mode == "🏦 Back to Bank":
        st.subheader("Back to Bank")
        conn = get_db_connection()
        # Nur Bargeld-Kategorien (Variable) zählen, die online ausgegeben wurden
        q = """SELECT SUM(t.amount) FROM transactions t LEFT JOIN categories c ON t.category = c.name 
               WHERE t.type='IST' AND t.is_online=1 AND (c.is_fixed=0 OR c.is_fixed IS NULL) AND (c.is_cashless=0 OR c.is_cashless IS NULL)"""
        online = pd.read_sql_query(q, conn).iloc[0,0] or 0.0
        dep = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='BANK_DEPOSIT'", conn).iloc[0,0] or 0.0
        conn.close()
        bal = online - dep
        st.metric("Im Umschlag", format_euro(bal))
        if bal > 0:
            with st.form("bf"):
                d_amt = st.number_input("Betrag einzahlen", value=float(bal), max_value=float(bal), format="%.2f")
                if st.form_submit_button("Einzahlen", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)", (date.today(), "Back to Bank", "Einzahlung", d_amt, "BANK_DEPOSIT", date.today().strftime("%Y-%m")))
                    st.success("✅")
                    st.rerun()
        else: st.success("Leer.")
        
    # 5. TOOLS
    elif sb_mode == "🧮 Scheinrechner":
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
            new_cashless = c_cashless.checkbox("Bargeldlos?")
            
            if st.form_submit_button("Hinzufügen"):
                if new_name:
                    if add_category_to_db(new_name, new_prio, 1 if new_fix else 0, 1 if new_cashless else 0):
                        st.success(f"OK")
                        if "bulk_df" in st.session_state: del st.session_state.bulk_df
                        st.rerun()
                    else: st.error("Existiert bereits.")
        
        st.divider()
        st.caption("Bearbeiten")
        edit_cat = st.selectbox("Auswahl", current_categories)
        if edit_cat:
            row = cat_df[cat_df['name'] == edit_cat].iloc[0]
            with st.form("edit_cat_form"):
                try: p_idx = PRIO_OPTIONS.index(row['priority'])
                except: p_idx = 3
                ep = st.selectbox("Prio", PRIO_OPTIONS, index=p_idx)
                
                c_e_fix, c_e_cl = st.columns(2)
                ef = c_e_fix.checkbox("Fixkosten?", value=(row['is_fixed']==1))
                ecl = c_e_cl.checkbox("Bargeldlos?", value=(row['is_cashless']==1))
                ed = st.number_input("Std. Budget", value=float(row.get('default_budget', 0.0)), step=10.0)
                
                c_save, c_del = st.columns(2)
                saved = c_save.form_submit_button("Speichern")
                deleted = c_del.form_submit_button("Löschen", type="primary")
                
                if saved:
                    execute_db("UPDATE categories SET priority=?, is_fixed=?, is_cashless=?, default_budget=? WHERE name=?", (ep, 1 if ef else 0, 1 if ecl else 0, ed, edit_cat))
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.success("OK")
                    st.rerun()
                if deleted:
                    delete_category_from_db(edit_cat)
                    if "bulk_df" in st.session_state: del st.session_state.bulk_df
                    st.rerun()
        
        st.divider()
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Backup", csv, "budget_backup.csv", "text/csv")
        
        st.divider()
        if st.checkbox("Reset freischalten"):
            if st.button("🧹 Nur Buchungen löschen", type="primary"):
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM sqlite_sequence WHERE name='transactions'")
                st.rerun()
            if st.button("💥 Alles löschen", type="primary"):
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM categories"); execute_db("DELETE FROM loans"); execute_db("DELETE FROM subscriptions"); execute_db("DELETE FROM sqlite_sequence")
                st.rerun()

# --- MAIN TABS ---
if df.empty and not current_categories:
    # 8 Tabs
    t_dash, t_sf, t_ana, t_sub, t_loan, t_comp, t_dat, t_hlp = st.tabs(["📊 Übersicht", "🎯 Sparziele", "📈 Analyse", "🔄 Abos", "📉 Kredite", "⚖️ Vergleich", "📝 Daten", "📖 Anleitung"])
    st.info("Start: Lege in der Sidebar Kategorien an.")
else:
    # 8 Tabs: Dashboard, Sparziele, Analyse, Abos, Kredite, Vergleich, Daten, Anleitung
    tab_dash, tab_sf, tab_ana, tab_subs, tab_loans, tab_comp, tab_data, tab_help = st.tabs(["📊 Übersicht", "🎯 Sparziele", "📈 Analyse", "🔄 Abos", "📉 Kredite", "⚖️ Vergleich", "📝 Daten", "📖 Hilfe"])

    # 1. DASHBOARD
    with tab_dash:
        # FIXKOSTEN RADAR
        st.markdown("##### 📌 Fixkosten (Monat)")
        
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
        cf1.metric("Ø Abos", format_euro(sub_monthly))
        cf2.metric("Kredite", format_euro(loan_monthly))
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

    # 2. SINKING
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
        
        # Rate
        total_monthly_need = sfd[sfd['target_amount'] > 0]['Rate'].sum()
        prio_sums = sfd[sfd['target_amount'] > 0].groupby('priority')['Rate'].sum()
        sum_a = prio_sums.get('A - Hoch', 0.0)
        sum_b = prio_sums.get('B - Mittel', 0.0)
        sum_c = prio_sums.get('C - Niedrig', 0.0)
        
        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("Gesamtrate / Monat", format_euro(total_monthly_need))
        kc2.metric("Prio A", format_euro(sum_a))
        kc3.metric("Prio B", format_euro(sum_b))
        kc4.metric("Prio C", format_euro(sum_c))
        st.divider()
        
        for p in PRIO_OPTIONS:
            g = sfd[sfd['priority'] == p].reset_index()
            if not g.empty:
                st.markdown(f"**{p}**")
                ek = f"sf_{p}"
                col_cfg = {
                    "name": st.column_config.TextColumn("Kategorie", disabled=True),
                    "Aktuell": st.column_config.NumberColumn("Ist-Stand", format="%.2f €", disabled=True),
