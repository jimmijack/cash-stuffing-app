import streamlit as st
import pandas as pd
import sqlite3
import datetime
import io
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
    </style>
""", unsafe_allow_html=True)

DB_FILE = "/data/budget.db"

DE_MONTHS = {1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni", 7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"}
DEFAULT_CATEGORIES = ["Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", "Sonstiges", "Fixkosten", "Kleidung", "Geschenke", "Notgroschen"]
PRIO_OPTIONS = ["A - Hoch", "B - Mittel", "C - Niedrig", "Standard"]

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
    c.execute('''CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, priority TEXT DEFAULT 'Standard', target_amount REAL DEFAULT 0.0, due_date TEXT, notes TEXT, is_fixed INTEGER DEFAULT 0, default_budget REAL DEFAULT 0.0)''')
    
    # NEU: Kredite Tabelle
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        start_date TEXT,
        total_amount REAL,
        interest_rate REAL,
        term_months INTEGER,
        monthly_payment REAL
    )''')
    
    # Migrations
    try: c.execute("SELECT default_budget FROM categories LIMIT 1")
    except: c.execute("ALTER TABLE categories ADD COLUMN default_budget REAL DEFAULT 0.0")
    
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

# --- Fehlende Funktionen Wrapper ---
def add_category_to_db(new_cat, prio, is_fixed=0):
    return execute_db("INSERT INTO categories (name, priority, is_fixed) VALUES (?, ?, ?)", (new_cat, prio, is_fixed))

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
    if 'is_fixed' not in df.columns: df['is_fixed'] = 0
    if 'default_budget' not in df.columns: df['default_budget'] = 0.0
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
    sb_mode = st.segmented_control("Menü", ["📝 Neu", "💰 Verteiler", "💸 Transfer", "🏦 Bank", "📉 Kredite", "🧮 Tools"], selection_mode="single", default="📝 Neu")
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
                is_fixed_cat = cat_df[cat_df['name'] == cat_input]['is_fixed'].iloc[0] == 1
                amt_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
                desc_input = st.text_input("Text")
                is_online = st.checkbox("💳 Online?", value=is_fixed_cat) if "IST" in type_input else False
                
                if st.form_submit_button("Speichern", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                               (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
                    st.toast("✅ Gespeichert!")
                    st.rerun()
            else: st.error("Keine Kategorien.")

    # 2. VERTEILER
    elif sb_mode == "💰 Verteiler":
        st.subheader("Budget Verteiler")
        bulk_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        today = date.today()
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        opt1, opt2 = f"{DE_MONTHS[today.month]} {today.year}", f"{DE_MONTHS[nm.month]} {nm.year}"
        bulk_target_sel = st.radio("Ziel", [opt1, opt2], horizontal=True)
        bulk_month = today.strftime("%Y-%m") if bulk_target_sel == opt1 else nm.strftime("%Y-%m")

        if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
            temp = cat_df[['name', 'is_fixed', 'default_budget']].copy()
            temp.columns = ['Kategorie', 'is_fixed', 'Betrag']
            st.session_state.bulk_df = temp

        st.caption("Werte basieren auf deinen Standard-Budgets (siehe Verwaltung).")
        edited = st.data_editor(
            st.session_state.bulk_df,
            column_config={
                "Kategorie": st.column_config.TextColumn(disabled=True),
                "Betrag": st.column_config.NumberColumn(format="%.2f", min_value=0),
                "is_fixed": st.column_config.CheckboxColumn("Fix?", disabled=True, width="small")
            },
            hide_index=True, use_container_width=True, height=400
        )
        
        total = edited["Betrag"].sum()
        fixed_sum = edited[edited['is_fixed']==1]['Betrag'].sum()
        cash_sum = total - fixed_sum
        
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("Gesamt", format_euro(total))
        c2.metric("Bar benötigt", format_euro(cash_sum), help="Nur variable Kosten")
        
        if st.button("Buchen", type="primary", use_container_width=True):
            if total > 0:
                c = 0
                for _, row in edited.iterrows():
                    if row["Betrag"] > 0:
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (bulk_date, row["Kategorie"], "Verteiler", row["Betrag"], "SOLL", bulk_month, 0))
                        c += 1
                st.success(f"✅ {c} Budgets gebucht!")
                st.session_state.bulk_df = cat_df[['name', 'is_fixed', 'default_budget']].rename(columns={'name':'Kategorie', 'default_budget':'Betrag'})
                st.rerun()

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
        q = "SELECT SUM(t.amount) FROM transactions t LEFT JOIN categories c ON t.category = c.name WHERE t.type='IST' AND t.is_online=1 AND c.is_fixed=0"
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

    # 5. KREDITE (ADD)
    elif sb_mode == "📉 Kredite":
        st.subheader("Kredit hinzufügen")
        with st.form("loan_add"):
            l_name = st.text_input("Name (z.B. PayPal Laptop)")
            l_sum = st.number_input("Kreditsumme (€)", min_value=0.0, step=50.0)
            l_rate = st.number_input("Rate (€/Monat)", min_value=0.0, step=10.0)
            l_zins = st.number_input("Zins (% p.a.)", min_value=0.0, step=0.1)
            l_start = st.date_input("Startdatum", date.today())
            l_term = st.number_input("Laufzeit (Monate)", min_value=1, value=12)
            
            if st.form_submit_button("Kredit anlegen", use_container_width=True):
                execute_db("INSERT INTO loans (name, start_date, total_amount, interest_rate, term_months, monthly_payment) VALUES (?,?,?,?,?,?)",
                           (l_name, l_start, l_sum, l_zins, l_term, l_rate))
                st.success("Gespeichert!")
                st.rerun()

    # 6. TOOLS
    elif sb_mode == "🧮 Tools":
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
        c_n, c_p = st.columns([2,1])
        new_name = c_n.text_input("Name", placeholder="Neue Kat.")
        new_prio = c_p.selectbox("Prio", PRIO_OPTIONS, label_visibility="collapsed")
        new_fix = st.checkbox("Ist Fixkosten?")
        if st.button("Hinzufügen"):
            if new_name:
                add_category_to_db(new_name, new_prio, 1 if new_fix else 0)
                st.rerun()
        
        st.divider()
        edit_cat = st.selectbox("Bearbeiten", current_categories)
        if edit_cat:
            row = cat_df[cat_df['name'] == edit_cat].iloc[0]
            try: p_idx = PRIO_OPTIONS.index(row['priority'])
            except: p_idx = 3
            ep = st.selectbox("Prio", PRIO_OPTIONS, index=p_idx)
            ef = st.checkbox("Fixkosten?", value=(row['is_fixed']==1))
            ed = st.number_input("Standard Budget (€)", value=float(row.get('default_budget', 0.0)), step=10.0)
            if st.button("Speichern"):
                execute_db("UPDATE categories SET priority=?, is_fixed=?, default_budget=? WHERE name=?", (ep, 1 if ef else 0, ed, edit_cat))
                st.rerun()
            if st.button("Löschen", type="primary"):
                delete_category_from_db(edit_cat)
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
                execute_db("DELETE FROM transactions"); execute_db("DELETE FROM categories"); execute_db("DELETE FROM loans"); execute_db("DELETE FROM sqlite_sequence")
                st.rerun()

# --- MAIN TABS ---
if df.empty and not current_categories:
    st.info("Start: Lege in der Sidebar Kategorien an.")
else:
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["📊 Dashboard", "🎯 Sparziele", "📉 Kredite", "📈 Analyse", "⚖️ Vergleich", "📝 Daten", "📖 Anleitung"])

    # T1
    with t1:
        if df.empty: st.info("Keine Daten.")
        else:
            col_m, col_cat = st.columns([1, 3])
            m_opts = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            if not m_opts.empty:
                sel_m = col_m.selectbox("Zeitraum", m_opts['Analyse_Monat'].unique(), label_visibility="collapsed")
                sel_c = col_cat.multiselect("Filter", current_categories, default=current_categories, label_visibility="collapsed")
                
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
                ov = ov.merge(cat_df.set_index('name')[['priority','is_fixed']], left_index=True, right_index=True, how='left')
                ov['priority'] = ov['priority'].fillna('Standard')
                
                s = ov.sum(numeric_only=True)
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Verfügbar", format_euro(s['Gesamt']), delta=f"Übertrag: {format_euro(s['Übertrag'])}")
                k2.metric("Ausgaben", format_euro(s['Ausgaben']), delta=f"{s['Quote']*100:.1f}%", delta_color="inverse")
                k3.metric("Rest", format_euro(s['Rest']), delta_color="normal")
                
                b2b = d_c[(d_c['is_online']==1) & (d_c['category'].isin(sel_c))].merge(cat_df, left_on='category', right_on='name')
                b2b_s = b2b[b2b['is_fixed']==0]['amount'].sum()
                if b2b_s > 0: k4.warning(f"Bank: {format_euro(b2b_s)}", icon="💳")
                else: k4.success("Bank: 0 €", icon="✅")
                
                st.markdown("### 📋 Übersicht")
                ov = ov.sort_values(by=['priority', 'Rest'], ascending=[True, False])
                cfg = {"Quote": st.column_config.ProgressColumn("Status", format="%.0f%%", min_value=0, max_value=1), "Übertrag": st.column_config.NumberColumn(format="%.2f €"), "Budget": st.column_config.NumberColumn(format="%.2f €"), "Gesamt": st.column_config.NumberColumn(format="%.2f €"), "Ausgaben": st.column_config.NumberColumn(format="%.2f €"), "Rest": st.column_config.NumberColumn(format="%.2f €"), "is_fixed": st.column_config.CheckboxColumn("Fix", width="small")}
                st.dataframe(ov[['priority','is_fixed','Übertrag','Budget','Gesamt','Ausgaben','Rest','Quote']], use_container_width=True, column_config=cfg, height=500)
                
                with st.expander("🔎 Details"):
                    ts = d_c[d_c['category'].isin(ov.index)].copy()
                    ts['M'] = ts['is_online'].apply(lambda x: "💳" if x==1 else "💵")
                    st.dataframe(ts[['date','category','description','amount','type','M']].sort_values(by='date', ascending=False), use_container_width=True, column_config={"amount": st.column_config.NumberColumn(format="%.2f €"), "date": st.column_config.DateColumn(format="DD.MM.YYYY")}, hide_index=True)

    # T2 Sinking
    with t2:
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
        
        for p in PRIO_OPTIONS:
            g = sfd[sfd['priority'] == p].reset_index()
            if not g.empty:
                st.markdown(f"**{p}**")
                ek = f"sf_{p}"
                ed = st.data_editor(g, key=ek, use_container_width=True, hide_index=True, column_order=["name","Aktuell","target_amount","due_date","Progress","Rate","Info","notes"], column_config={"name": st.column_config.TextColumn(disabled=True), "Aktuell": st.column_config.NumberColumn(format="%.2f €", disabled=True), "target_amount": st.column_config.NumberColumn(format="%.2f €", required=True), "due_date": st.column_config.DateColumn(format="DD.MM.YYYY"), "Progress": st.column_config.ProgressColumn(format="%.0f%%"), "Rate": st.column_config.NumberColumn(format="%.2f €", disabled=True), "Info": st.column_config.TextColumn(disabled=True)})
                
                if st.session_state[ek]["edited_rows"]:
                    for i, ch in st.session_state[ek]["edited_rows"].items():
                        cn = g.iloc[i]['name']
                        nt = ch.get("target_amount", g.iloc[i]['target_amount'])
                        nd = ch.get("due_date", g.iloc[i]['due_date'])
                        nn = ch.get("notes", g.iloc[i]['notes'])
                        if isinstance(nd, (datetime.datetime, pd.Timestamp)): nd = nd.strftime("%Y-%m-%d")
                        elif pd.isnull(nd): nd = None
                        execute_db("UPDATE categories SET target_amount=?, due_date=?, notes=? WHERE name=?", (nt, nd, nn, cn))
                    st.rerun()

    # T3 Kredite (NEU)
    with t3:
        st.subheader("📉 Kredit Übersicht")
        loans_df = get_data("SELECT * FROM loans")
        
        if loans_df.empty:
            st.info("Keine Kredite angelegt. Nutze die Sidebar.")
        else:
            loans_df['start_date'] = pd.to_datetime(loans_df['start_date'])
            
            # Berechnungen
            def calc_loan(row):
                end_date = row['start_date'] + relativedelta(months=row['term_months'])
                today = datetime.datetime.now()
                
                if today > end_date:
                    return "✅ Bezahlt", 1.0, 0.0, end_date
                
                # Monate vergangen
                diff = relativedelta(today, row['start_date'])
                months_passed = diff.years*12 + diff.months
                if months_passed < 0: months_passed = 0
                
                progress = months_passed / row['term_months']
                
                # Sehr grobe Restschuld Schätzung (Linear)
                # Genauer geht es nur mit Amortisationsplan, aber das reicht für Overview
                paid = months_passed * row['monthly_payment']
                # Hier nehmen wir vereinfacht an: Restlaufzeit * Rate = Restschuld (inkl Zins)
                remaining_months = row['term_months'] - months_passed
                remaining_amount = remaining_months * row['monthly_payment']
                
                return f"Noch {remaining_months} Mon.", progress, remaining_amount, end_date

            res = loans_df.apply(calc_loan, axis=1, result_type='expand')
            loans_df['Status'] = res[0]
            loans_df['Progress'] = res[1]
            loans_df['Rest (ca.)'] = res[2]
            loans_df['Ende'] = res[3]
            
            # KPIs
            total_monthly = loans_df[loans_df['Ende'] > datetime.datetime.now()]['monthly_payment'].sum()
            total_debt = loans_df['Rest (ca.)'].sum()
            debt_free_date = loans_df['Ende'].max().strftime("%b %Y")
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Monatliche Rate (Gesamt)", format_euro(total_monthly))
            c2.metric("Restschuld (ca. inkl. Zins)", format_euro(total_debt))
            c3.metric("Schuldenfrei ab", debt_free_date)
            
            # Highlight highest Interest
            max_int_idx = loans_df['interest_rate'].idxmax()
            st.caption(f"🔥 Fokus-Empfehlung (Lawine): **{loans_df.loc[max_int_idx, 'name']}** hat mit {loans_df.loc[max_int_idx, 'interest_rate']}% den höchsten Zins.")
            
            # Editor
            loan_cfg = {
                "id": st.column_config.NumberColumn(disabled=True),
                "name": st.column_config.TextColumn("Kredit"),
                "start_date": st.column_config.DateColumn("Start"),
                "total_amount": st.column_config.NumberColumn("Kreditsumme", format="%.2f €"),
                "interest_rate": st.column_config.NumberColumn("Zins %"),
                "term_months": st.column_config.NumberColumn("Laufzeit (M)"),
                "monthly_payment": st.column_config.NumberColumn("Rate", format="%.2f €"),
                "Progress": st.column_config.ProgressColumn("Fortschritt", format="%.0f%%"),
                "Rest (ca.)": st.column_config.NumberColumn(format="%.2f €", disabled=True),
                "Ende": st.column_config.DateColumn(format="DD.MM.YYYY", disabled=True),
                "Status": st.column_config.TextColumn(disabled=True)
            }
            
            edited_loans = st.data_editor(
                loans_df, 
                key="loan_editor",
                hide_index=True,
                use_container_width=True,
                column_config=loan_cfg,
                column_order=["name", "monthly_payment", "Rest (ca.)", "Progress", "Status", "interest_rate", "total_amount", "start_date", "term_months", "Ende"]
            )
            
            # Save Logic
            if st.session_state["loan_editor"]:
                chg = st.session_state["loan_editor"]
                for i in chg["deleted_rows"]: 
                    execute_db("DELETE FROM loans WHERE id=?", (int(loans_df.iloc[i]['id']),))
                for i, v in chg["edited_rows"].items():
                    lid = loans_df.iloc[i]['id']
                    for k, val in v.items():
                        # Date fix
                        if k == 'start_date':
                             if isinstance(val, (datetime.datetime, pd.Timestamp)): val = val.strftime("%Y-%m-%d")
                        execute_db(f"UPDATE loans SET {k}=? WHERE id=?", (val, int(lid)))
                
                if chg["deleted_rows"] or chg["edited_rows"]: st.rerun()

    # T4 Analyse
    with t4:
        st.subheader("Analyse")
        if df.empty: st.info("Leer.")
        else:
            di = df[df['type']=='IST'].copy()
            if di.empty: st.info("Keine Ausgaben.")
            else:
                c1, c2 = st.columns(2)
                with c1: st.plotly_chart(px.pie(di, values='amount', names='category', title='Kategorien'), use_container_width=True)
                with c2: st.plotly_chart(px.bar(di.groupby(['budget_month','category'])['amount'].sum().reset_index(), x='budget_month', y='amount', color='category', title='Trend'), use_container_width=True)

    # T5 Vergleich
    with t5:
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

    # T6 Data
    with t6:
        st.subheader("Editor")
        de = get_data("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        if not de.empty: de['date'] = pd.to_datetime(de['date'])
        cf = {"id": st.column_config.NumberColumn(disabled=True), "date": st.column_config.DateColumn(format="DD.MM.YYYY"), "category": st.column_config.SelectboxColumn(options=current_categories + ["Back to Bank"]), "type": st.column_config.SelectboxColumn(options=["IST", "SOLL", "BANK_DEPOSIT"]), "amount": st.column_config.NumberColumn(format="%.2f €"), "is_online": st.column_config.CheckboxColumn()}
        er = st.data_editor(de, hide_index=True, use_container_width=True, column_config=cf, key="me", num_rows="dynamic")
        
        if st.session_state["me"]:
            ch = st.session_state["me"]
            for i in ch["deleted_rows"]: execute_db("DELETE FROM transactions WHERE id=?", (int(de.iloc[i]['id']),))
            for i, v in ch["edited_rows"].items():
                rid = de.iloc[i]['id']
                for k, val in v.items():
                    if k=='is_online': val=1 if val else 0
                    execute_db(f"UPDATE transactions SET {k}=? WHERE id=?", (val, int(rid)))
            for r in ch["added_rows"]:
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                           (r.get('date', date.today()), r.get('category', 'Sonstiges'), r.get('description', ''), r.get('amount', 0), r.get('type', 'IST'), r.get('budget_month', date.today().strftime('%Y-%m')), 1 if r.get('is_online') else 0))
            if ch["deleted_rows"] or ch["edited_rows"] or ch["added_rows"]: st.rerun()

    # T7 Anleitung
    with t7:
        st.subheader("📖 Anleitung & Workflow")
        
        with st.expander("1️⃣ Einrichtung (Einmalig)", expanded=True):
            st.markdown("""
            1. Gehe in der Sidebar (links) ganz unten zu **⚙️ Verwaltung**.
            2. Erstelle deine Kategorien (z.B. *Lebensmittel, Miete, Urlaub*).
            3. **WICHTIG:** Wenn eine Kategorie nur vom Konto abgeht (z.B. Miete, Netflix), setze den Haken bei **"Ist Fixkosten?"**. 
               *Diese tauchen dann nicht im "Bar benötigt"-Rechner auf.*
            4. Lege bei Bedarf ein **Standard-Budget** fest, um den Monatsstart zu beschleunigen.
            """)
            
        with st.expander("2️⃣ Monatsanfang (Geld verteilen)", expanded=True):
            st.markdown("""
            1. Wähle in der Sidebar **💰 Verteiler**.
            2. Wähle das Datum und den Ziel-Monat.
            3. Die Tabelle ist mit deinen Standard-Budgets vorausgefüllt. Passe die Werte an.
            4. Unten siehst du **"Bar benötigt"**. Das ist die Summe, die du am Automaten abheben musst (für deine Umschläge).
            5. Klicke auf **"Budgets buchen"**. Alle SOLL-Werte sind nun im System.
            """)
            
        with st.expander("3️⃣ Im Alltag (Ausgaben erfassen)", expanded=True):
            st.markdown("""
            1. Wähle in der Sidebar **📝 Neu**.
            2. Wähle **IST (Ausgabe)**.
            3. Gib Betrag und Kategorie ein.
            4. **Hybrid-Check:**
               * Hast du mit Bargeld aus dem Umschlag bezahlt? ➔ **Kein Haken**.
               * Hast du mit Karte/PayPal/Uber bezahlt? ➔ **Setze Haken bei "💳 Online?"**.
                 *(Das System merkt sich nun, dass du dieses Geld eigentlich noch bar im Umschlag hast, es aber auf das Konto muss)*.
            """)
            
        with st.expander("4️⃣ Hybrid-System (Back to Bank)"):
            st.markdown("""
            Wenn du oft online zahlst, sammelt sich Bargeld in deinen Umschlägen, das eigentlich auf dem Konto fehlt.
            1. Gehe in der Sidebar zu **🏦 Bank**.
            2. Du siehst "Im Umschlag: X €".
            3. Nimm genau diesen Betrag aus deinen variablen Umschlägen.
            4. Zahle ihn am Automaten auf dein Konto ein.
            5. Klicke in der App auf **"Als eingezahlt markieren"**. Der virtuelle "Back to Bank"-Topf ist nun wieder leer.
            """)
            
        with st.expander("5️⃣ Sinking Funds (Sparziele)"):
            st.markdown("""
            1. Gehe zum Tab **🎯 Sparziele**.
            2. Klicke in die Tabelle, um **Zielbetrag** und **Fälligkeitsdatum** einzutragen.
            3. Die App berechnet dir automatisch, wie viel du monatlich sparen musst ("Rate").
            4. Priorisiere Töpfe (A, B, C) in der Verwaltung, um die Liste zu sortieren.
            """)
