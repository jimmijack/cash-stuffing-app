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

# Custom CSS - Theme Aware (Dark/Light Mode kompatibel)
st.markdown("""
    <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
        
        /* Metrik-Boxen stylen */
        div[data-testid="stMetric"] {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            color: var(--text-color);
        }
        
        /* Tabellen Header (Index verstecken) */
        thead tr th:first-child {display:none}
        tbody th {display:none}
    </style>
""", unsafe_allow_html=True)

# Datenbank Pfad
DB_FILE = "/data/budget.db"

# Konstanten
DE_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}
DEFAULT_CATEGORIES = [
    "Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", 
    "Sonstiges", "Fixkosten", "Kleidung", "Geschenke", "Notgroschen"
]
PRIO_OPTIONS = ["A - Hoch", "B - Mittel", "C - Niedrig", "Standard"]

# --- 2. HELPER FUNKTIONEN ---
def format_euro(val):
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

def get_db_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Tables erstellen
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, description TEXT, 
        amount REAL, type TEXT, budget_month TEXT, is_online INTEGER DEFAULT 0)''')
        
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        name TEXT PRIMARY KEY, priority TEXT DEFAULT 'Standard', 
        target_amount REAL DEFAULT 0.0, due_date TEXT, notes TEXT, is_fixed INTEGER DEFAULT 0)''')
    
    # Initiale Daten
    c.execute("SELECT count(*) FROM categories")
    if c.fetchone()[0] == 0:
        for cat in DEFAULT_CATEGORIES:
            is_fix = 1 if cat in ["Miete", "Fixkosten"] else 0
            c.execute("INSERT OR IGNORE INTO categories (name, priority, is_fixed) VALUES (?, ?, ?)", (cat, "Standard", is_fix))
    conn.commit()
    conn.close()

# Datenbank-Operationen gekapselt
def get_data(query, params=()):
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(query, conn, params=params)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def execute_db(query, params=()):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

# --- 3. LOGIK & DATENLADEN ---
def load_main_data():
    df = get_data("SELECT * FROM transactions")
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['budget_month'] = df['budget_month'].fillna(df['date'].dt.strftime('%Y-%m'))
        df['is_online'] = df['is_online'].fillna(0).astype(int)
        
        # Analyse-Monat berechnen
        def get_analysis_month(row):
            if row['type'] == 'SOLL':
                try:
                    y, m = map(int, row['budget_month'].split('-'))
                    return f"{DE_MONTHS[m]} {y}"
                except: pass
            return f"{DE_MONTHS[row['date'].month]} {row['date'].year}"

        df['Analyse_Monat'] = df.apply(get_analysis_month, axis=1)
        
        # Sort Key
        def get_sort_key(row):
            if row['type'] == 'SOLL':
                try:
                    parts = row['budget_month'].split('-')
                    return int(parts[0]) * 100 + int(parts[1])
                except: pass
            return row['date'].year * 100 + row['date'].month
        
        df['sort_key_month'] = df.apply(get_sort_key, axis=1)
        df['Jahr'] = df['date'].dt.year
        df['Quartal'] = "Q" + df['date'].dt.quarter.astype(str) + " " + df['Jahr'].astype(str)
        
    return df

def get_categories_full():
    df = get_data("SELECT * FROM categories ORDER BY name ASC")
    if 'is_fixed' not in df.columns: df['is_fixed'] = 0
    df['is_fixed'] = df['is_fixed'].fillna(0).astype(int)
    return df

# Initialisierung
try: init_db()
except: pass # Silent fail für Docker build phase

# --- 4. UI START ---
df = load_main_data()
cat_df = get_categories_full()
current_categories = cat_df['name'].tolist() if not cat_df.empty else []

st.title("💶 Cash Stuffing Planer")

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("### 🧭 Navigation")
    
    # TAB SYSTEM SIDEBAR
    sb_mode = st.segmented_control(
        "Aktion wählen", 
        ["📝 Neu", "💰 Verteiler", "💸 Transfer", "🏦 Bank"], 
        selection_mode="single", default="📝 Neu"
    )
    
    st.divider()

    # --- 1. NEUER EINTRAG ---
    if sb_mode == "📝 Neu":
        st.subheader("Buchung erfassen")
        with st.form("entry_form", clear_on_submit=True):
            col_d, col_t = st.columns([1,1])
            date_input = col_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
            type_input = col_t.selectbox("Typ", ["IST (Ausgabe)", "SOLL (Budget)"])
            
            budget_target = None
            if "SOLL" in type_input:
                today = date.today()
                nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
                opt1 = f"{DE_MONTHS[today.month]} {today.year}"
                opt2 = f"{DE_MONTHS[nm.month]} {nm.year}"
                bm_sel = st.radio("Ziel-Monat", [opt1, opt2], horizontal=True)
                budget_target = today.strftime("%Y-%m") if bm_sel == opt1 else nm.strftime("%Y-%m")
            
            if not current_categories:
                st.error("Bitte erst Kategorien anlegen!")
            else:
                cat_input = st.selectbox("Kategorie", current_categories)
                # Check ob Fixkosten
                is_fixed_cat = cat_df[cat_df['name'] == cat_input]['is_fixed'].iloc[0] == 1
                
                amt_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
                desc_input = st.text_input("Beschreibung")
                
                is_online = False
                if "IST" in type_input:
                    # Smart Default: Fixkosten sind meist Online
                    is_online = st.checkbox("💳 Online / Karte?", value=is_fixed_cat)
                
                if st.form_submit_button("Speichern", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                               (date_input, cat_input, desc_input, amt_input, "SOLL" if "SOLL" in type_input else "IST", budget_target, 1 if is_online else 0))
                    st.toast("✅ Buchung gespeichert!")
                    st.rerun()

    # --- 2. VERTEILER ---
    elif sb_mode == "💰 Verteiler":
        st.subheader("Budget Verteiler")
        
        col_d, col_check = st.columns([1,1])
        bulk_date = col_d.date_input("Datum", date.today(), format="DD.MM.YYYY")
        
        today = date.today()
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        opt1 = f"{DE_MONTHS[today.month]} {today.year}"
        opt2 = f"{DE_MONTHS[nm.month]} {nm.year}"
        bulk_target_sel = st.radio("Für Monat:", [opt1, opt2], horizontal=True)
        bulk_month = today.strftime("%Y-%m") if bulk_target_sel == opt1 else nm.strftime("%Y-%m")

        # Session State für Verteiler
        if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(cat_df):
            temp = pd.DataFrame({"Kategorie": cat_df['name'], "Betrag": 0.0})
            # Fixkosten Flag mergen
            temp = temp.merge(cat_df[['name', 'is_fixed']], left_on='Kategorie', right_on='name', how='left')
            st.session_state.bulk_df = temp

        edited = st.data_editor(
            st.session_state.bulk_df,
            column_config={
                "Kategorie": st.column_config.TextColumn("Kategorie", disabled=True),
                "Betrag": st.column_config.NumberColumn("€", min_value=0, format="%.2f"),
                "is_fixed": st.column_config.CheckboxColumn("Fix?", disabled=True, width="small"),
                "name": None # Hide merged column
            },
            hide_index=True,
            use_container_width=True,
            height=400
        )
        
        total = edited["Betrag"].sum()
        fixed_sum = edited[edited['is_fixed']==1]['Betrag'].sum()
        
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("Gesamt", format_euro(total))
        c2.metric("Bar/Umschlag", format_euro(total-fixed_sum), delta="Abzuheben", delta_color="off")
        
        if st.button("Budgets buchen", type="primary", use_container_width=True):
            if total > 0:
                count = 0
                for _, row in edited.iterrows():
                    if row["Betrag"] > 0:
                        execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                                   (bulk_date, row["Kategorie"], "Verteiler", row["Betrag"], "SOLL", bulk_month, 0))
                        count += 1
                # Reset
                st.session_state.bulk_df["Betrag"] = 0.0
                st.success(f"✅ {count} Budgets für {bulk_target_sel} angelegt!")
                st.rerun()
            else:
                st.warning("Summe ist 0.")

    # --- 3. TRANSFER ---
    elif sb_mode == "💸 Transfer":
        st.subheader("Umbuchung")
        with st.form("trf_form"):
            t_date = st.date_input("Datum", date.today())
            c_from = st.selectbox("Von (Quelle)", current_categories)
            c_to = st.selectbox("Nach (Ziel)", current_categories, index=1 if len(current_categories)>1 else 0)
            t_amt = st.number_input("Betrag (€)", min_value=0.01, format="%.2f")
            
            if st.form_submit_button("Umbuchen", use_container_width=True):
                if c_from != c_to:
                    # Abgang Quelle (Negatives Budget)
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)",
                               (t_date, c_from, f"Zu {c_to}", -t_amt, "SOLL", t_date.strftime("%Y-%m")))
                    # Zugang Ziel (Positives Budget)
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)",
                               (t_date, c_to, f"Von {c_from}", t_amt, "SOLL", t_date.strftime("%Y-%m")))
                    st.success("✅ Erledigt!")
                    st.rerun()
                else:
                    st.error("Kategorien identisch.")

    # --- 4. BACK TO BANK ---
    elif sb_mode == "🏦 Bank":
        st.subheader("Back to Bank")
        
        # Berechnung Live
        conn = get_db_connection()
        # Online Ausgaben (nur variable Kosten)
        q_online = "SELECT SUM(t.amount) FROM transactions t LEFT JOIN categories c ON t.category = c.name WHERE t.type='IST' AND t.is_online=1 AND c.is_fixed=0"
        online_sum = pd.read_sql_query(q_online, conn).iloc[0,0] or 0.0
        # Bereits eingezahlt
        dep_sum = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='BANK_DEPOSIT'", conn).iloc[0,0] or 0.0
        conn.close()
        
        b2b = online_sum - dep_sum
        
        st.metric("Im Umschlag", format_euro(b2b), help="Summe der variablen Ausgaben, die online getätigt wurden.")
        
        if b2b > 0:
            st.info("Bitte Geld einzahlen.")
            with st.form("bank_form"):
                d_date = st.date_input("Datum", date.today())
                d_amt = st.number_input("Betrag", value=float(b2b), max_value=float(b2b), format="%.2f")
                if st.form_submit_button("Als eingezahlt markieren", use_container_width=True):
                    execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?,?,?,?,?,?)",
                               (d_date, "Back to Bank", "Einzahlung", d_amt, "BANK_DEPOSIT", d_date.strftime("%Y-%m")))
                    st.success("✅ Vergebucht!")
                    st.rerun()
        else:
            st.success("Alles ausgeglichen.")

    # --- FOOTER SETTINGS ---
    st.markdown("---")
    with st.expander("⚙️ Verwaltung"):
        # Add Cat
        c_n, c_p = st.columns([2,1])
        new_name = c_n.text_input("Name", placeholder="Neue Kat.")
        new_prio = c_p.selectbox("Prio", PRIO_OPTIONS, label_visibility="collapsed")
        new_fix = st.checkbox("Ist Fixkosten?")
        if st.button("Hinzufügen"):
            if new_name:
                add_category_to_db(new_name, new_prio, 1 if new_fix else 0)
                st.rerun()
        
        st.divider()
        # Edit Cat
        edit_cat = st.selectbox("Bearbeiten", current_categories)
        if edit_cat:
            row = cat_df[cat_df['name'] == edit_cat].iloc[0]
            try: p_idx = PRIO_OPTIONS.index(row['priority'])
            except: p_idx = 3
            
            e_prio = st.selectbox("Prio ändern", PRIO_OPTIONS, index=p_idx)
            e_fix = st.checkbox("Fixkosten?", value=(row['is_fixed']==1))
            
            if st.button("Speichern"):
                execute_db("UPDATE categories SET priority=?, is_fixed=? WHERE name=?", (e_prio, 1 if e_fix else 0, edit_cat))
                st.rerun()
            if st.button("Löschen", type="primary"):
                delete_category_from_db(edit_cat)
                st.rerun()

# --- HAUPTBEREICH TABS ---
if df.empty and not current_categories:
    st.info("👋 Willkommen! Bitte erstelle zuerst Kategorien in der Seitenleiste (⚙️ Verwaltung).")
else:
    t1, t2, t3, t4, t5 = st.tabs(["📊 Dashboard", "🎯 Sparziele (Sinking Funds)", "📈 Analyse", "⚖️ Vergleich", "📝 Daten"])

    # --- DASHBOARD (TAB 1) ---
    with t1:
        # Filter Leiste
        col_m, col_cat = st.columns([1, 3])
        
        m_opts = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
        if not m_opts.empty:
            sel_month = col_m.selectbox("Zeitraum", m_opts['Analyse_Monat'].unique(), label_visibility="collapsed")
            sel_cats = col_cat.multiselect("Filter", current_categories, default=current_categories, label_visibility="collapsed", placeholder="Alle Kategorien")
            
            curr_key = m_opts[m_opts['Analyse_Monat'] == sel_month]['sort_key_month'].iloc[0]
            
            # Daten filtern
            # Nur SOLL und IST für die Übersicht (keine Bank Transfers)
            mask_month = df['sort_key_month'] == curr_key
            mask_prev = df['sort_key_month'] < curr_key
            mask_type = df['type'].isin(['SOLL', 'IST'])
            
            df_curr = df[mask_month & mask_type].copy()
            df_prev = df[mask_prev & mask_type].copy()
            
            # Berechnung Übertrag
            prev_grp = df_prev.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in prev_grp: prev_grp['SOLL'] = 0
            if 'IST' not in prev_grp: prev_grp['IST'] = 0
            carryover = prev_grp['SOLL'] - prev_grp['IST']
            
            # Berechnung Aktuell
            curr_grp = df_curr.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in curr_grp: curr_grp['SOLL'] = 0
            if 'IST' not in curr_grp: curr_grp['IST'] = 0
            
            # Merge
            overview = pd.DataFrame({'Übertrag': carryover, 'Budget': curr_grp['SOLL'], 'Ausgaben': curr_grp['IST']}).fillna(0)
            
            # Kategorie Filter anwenden
            if sel_cats: overview = overview[overview.index.isin(sel_cats)]
            else: overview = overview[overview.index.isin([])] # Empty if nothing selected
            
            # Berechnungen
            overview['Gesamt'] = overview['Übertrag'] + overview['Budget']
            overview['Rest'] = overview['Gesamt'] - overview['Ausgaben']
            overview['Quote'] = (overview['Ausgaben'] / overview['Gesamt']).fillna(0)
            
            # Merge Metadaten (Prio, Fix)
            overview = overview.merge(cat_df.set_index('name')[['priority', 'is_fixed']], left_index=True, right_index=True, how='left')
            overview['priority'] = overview['priority'].fillna('Standard')
            
            # KPIs Top Row
            sums = overview.sum(numeric_only=True)
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("Verfügbar (Gesamt)", format_euro(sums['Gesamt']), delta=f"Übertrag: {format_euro(sums['Übertrag'])}")
            kpi2.metric("Ausgaben", format_euro(sums['Ausgaben']), delta=f"{sums['Quote']*100:.1f}%", delta_color="inverse")
            kpi3.metric("Restbetrag", format_euro(sums['Rest']), delta_color="normal")
            
            # Back to Bank Alert für diesen Monat (Nur Variable Kosten)
            # Wir berechnen das separat, da 'overview' auch Fixkosten enthalten kann
            b2b_month = df_curr[(df_curr['is_online']==1) & (df_curr['category'].isin(sel_cats))].merge(cat_df, left_on='category', right_on='name')
            b2b_month_sum = b2b_month[b2b_month['is_fixed']==0]['amount'].sum()
            
            if b2b_month_sum > 0:
                kpi4.warning(f"🏦 Zur Bank: {format_euro(b2b_month_sum)}", icon="💳")
            else:
                kpi4.success("Keine Bank-Rücklage nötig", icon="✅")

            # Haupttabelle mit st.dataframe column config
            st.markdown("### 📋 Budget Übersicht")
            
            # Sortierung
            overview = overview.sort_values(by=['priority', 'Rest'], ascending=[True, False])
            
            # Spalten Konfiguration für hübsches UI
            cfg = {
                "Quote": st.column_config.ProgressColumn("Status", format="%.0f%%", min_value=0, max_value=1),
                "Übertrag": st.column_config.NumberColumn("Übertrag", format="%.2f €"),
                "Budget": st.column_config.NumberColumn("Neu (+)", format="%.2f €"),
                "Gesamt": st.column_config.NumberColumn("Verfügbar", format="%.2f €"),
                "Ausgaben": st.column_config.NumberColumn("Ist (-)", format="%.2f €"),
                "Rest": st.column_config.NumberColumn("Rest (=)", format="%.2f €"),
                "priority": st.column_config.TextColumn("Prio"),
                "is_fixed": st.column_config.CheckboxColumn("Fix", width="small")
            }
            
            # DataFrame aufräumen
            show_df = overview[['priority', 'is_fixed', 'Übertrag', 'Budget', 'Gesamt', 'Ausgaben', 'Rest', 'Quote']].copy()
            
            st.dataframe(show_df, use_container_width=True, column_config=cfg, height=500)
            
            # Einzelbuchungen
            with st.expander("🔎 Einzelbuchungen ansehen"):
                # Filter current selection
                trans_show = df_curr[df_curr['category'].isin(overview.index)].copy()
                trans_show['Mode'] = trans_show['is_online'].apply(lambda x: "💳" if x==1 else "💵")
                st.dataframe(
                    trans_show[['date', 'category', 'description', 'amount', 'type', 'Mode']].sort_values(by='date', ascending=False),
                    use_container_width=True,
                    column_config={
                        "amount": st.column_config.NumberColumn("Betrag", format="%.2f €"),
                        "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY")
                    },
                    hide_index=True
                )

    # --- SINKING FUNDS (TAB 2) ---
    with t2:
        st.subheader("🎯 Sparziele & Sinking Funds")
        
        # Berechnung IST-Stand (Total)
        sf_calc = df[df['type'].isin(['SOLL', 'IST'])].groupby('category')['amount'].apply(lambda x: x[df['type']=='SOLL'].sum() - x[df['type']=='IST'].sum())
        
        # Merge mit Zielen
        sf_df = cat_df.set_index('name').copy()
        sf_df['Aktuell'] = sf_calc
        sf_df['Aktuell'] = sf_df['Aktuell'].fillna(0.0)
        
        # Datums Fix
        sf_df['due_date'] = pd.to_datetime(sf_df['due_date'], errors='coerce')
        
        # Berechnung Sparrate
        def calc_rate(row):
            target = row['target_amount']
            if target <= 0: return 0.0, "Kein Ziel"
            curr = row['Aktuell']
            if curr >= target: return 0.0, "✅ Fertig"
            
            due = row['due_date']
            if pd.isnull(due): return 0.0, "Kein Datum"
            
            today = datetime.datetime.now()
            if due <= today: return (target-curr), "❗ Fällig"
            
            diff = relativedelta(due, today)
            months = diff.years * 12 + diff.months
            if months < 1: months = 1
            return (target-curr)/months, f"{months} Mon."

        res = sf_df.apply(calc_rate, axis=1, result_type='expand')
        sf_df['Rate'] = res[0]
        sf_df['Info'] = res[1]
        sf_df['Progress'] = (sf_df['Aktuell'] / sf_df['target_amount']).fillna(0).clip(0, 1)
        
        # Anzeige nach Prio Gruppen
        for prio in PRIO_OPTIONS:
            grp = sf_df[sf_df['priority'] == prio].reset_index()
            if not grp.empty:
                st.markdown(f"**{prio}**")
                
                # Editor Config
                ed_key = f"sf_ed_{prio}"
                edited = st.data_editor(
                    grp,
                    key=ed_key,
                    use_container_width=True,
                    hide_index=True,
                    column_order=["name", "Aktuell", "target_amount", "due_date", "Progress", "Rate", "Info", "notes"],
                    column_config={
                        "name": st.column_config.TextColumn("Topf", disabled=True),
                        "Aktuell": st.column_config.NumberColumn("Ist", format="%.2f €", disabled=True),
                        "target_amount": st.column_config.NumberColumn("Ziel (€)", min_value=0, format="%.2f €", required=True),
                        "due_date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
                        "Progress": st.column_config.ProgressColumn(" %", format="%.0f%%"),
                        "Rate": st.column_config.NumberColumn("Rate/Monat", format="%.2f €", disabled=True),
                        "Info": st.column_config.TextColumn("Zeit", disabled=True),
                        "notes": st.column_config.TextColumn("Notiz")
                    }
                )
                
                # Save Changes Logic
                if st.session_state[ed_key]["edited_rows"]:
                    for idx, chg in st.session_state[ed_key]["edited_rows"].items():
                        c_name = grp.iloc[idx]['name']
                        n_tgt = chg.get("target_amount", grp.iloc[idx]['target_amount'])
                        n_date = chg.get("due_date", grp.iloc[idx]['due_date'])
                        n_note = chg.get("notes", grp.iloc[idx]['notes'])
                        
                        # Date Convert
                        if isinstance(n_date, (datetime.datetime, pd.Timestamp)): n_date = n_date.strftime("%Y-%m-%d")
                        elif pd.isnull(n_date): n_date = None
                        
                        execute_db("UPDATE categories SET target_amount=?, due_date=?, notes=? WHERE name=?", (n_tgt, n_date, n_note, c_name))
                    st.rerun()

    # --- ANALYSE (TAB 3) ---
    with t3:
        st.subheader("Ausgaben Analyse")
        
        # Charts nur mit IST Daten
        df_ist = df[df['type'] == 'IST'].copy()
        
        c1, c2 = st.columns(2)
        with c1:
            # Pie Chart
            fig_pie = px.pie(df_ist, values='amount', names='category', title='Ausgaben nach Kategorie', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            # Bar Chart über Zeit
            df_bar = df_ist.groupby(['budget_month', 'category'])['amount'].sum().reset_index()
            fig_bar = px.bar(df_bar, x='budget_month', y='amount', color='category', title='Verlauf')
            st.plotly_chart(fig_bar, use_container_width=True)

    # --- VERGLEICH (TAB 4) ---
    with t4:
        st.subheader("Vergleichsrechner")
        periods = sorted(df['Analyse_Monat'].unique(), reverse=True)
        if len(periods) > 1:
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Basis", periods, index=0)
            p2 = c2.selectbox("Vergleich mit", periods, index=1)
            
            # Helper to get sums
            def get_sums(p):
                # Finde den numerischen Key
                key = m_opts[m_opts['Analyse_Monat'] == p]['sort_key_month'].iloc[0]
                d = df[(df['sort_key_month'] == key) & (df['type'] == 'IST')]
                return d.groupby('category')['amount'].sum()
            
            s1 = get_sums(p1)
            s2 = get_sums(p2)
            
            comp = pd.DataFrame({'Basis': s1, 'Vgl': s2}).fillna(0)
            comp['Diff'] = comp['Basis'] - comp['Vgl']
            
            st.dataframe(
                comp.style.format("{:.2f} €").background_gradient(cmap="RdYlGn_r", subset=['Diff']),
                use_container_width=True
            )
        else:
            st.info("Nicht genügend Daten für Vergleich.")

    # --- EDITOR (TAB 5) ---
    with t5:
        st.subheader("Datenbank Editor")
        st.info("Hier können Fehler korrigiert werden. Änderungen werden sofort gespeichert.")
        
        df_edit = get_data("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        
        # FIX: Datumsspalte von String zu Datetime konvertieren, damit st.data_editor zufrieden ist
        if not df_edit.empty:
            df_edit['date'] = pd.to_datetime(df_edit['date'])
        
        col_conf = {
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
            "category": st.column_config.SelectboxColumn("Kategorie", options=current_categories + ["Back to Bank"]),
            "type": st.column_config.SelectboxColumn("Typ", options=["IST", "SOLL", "BANK_DEPOSIT"]),
            "amount": st.column_config.NumberColumn("Betrag", format="%.2f €"),
            "is_online": st.column_config.CheckboxColumn("Online?"),
            "budget_month": st.column_config.TextColumn("Budget Monat")
        }
        
        edited_raw = st.data_editor(df_edit, hide_index=True, use_container_width=True, column_config=col_conf, key="main_editor", num_rows="dynamic")
        
        # Save Logic for Main Editor
        if st.session_state["main_editor"]:
            chg = st.session_state["main_editor"]
            
            # Delete
            for idx in chg["deleted_rows"]:
                rid = df_edit.iloc[idx]['id']
                execute_db("DELETE FROM transactions WHERE id=?", (int(rid),))
            
            # Edit
            for idx, vals in chg["edited_rows"].items():
                rid = df_edit.iloc[idx]['id']
                for k, v in vals.items():
                    # Boolean fix
                    if k == 'is_online': v = 1 if v else 0
                    execute_db(f"UPDATE transactions SET {k}=? WHERE id=?", (v, int(rid)))
            
            # Add
            for row in chg["added_rows"]:
                execute_db("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?,?,?,?,?,?,?)",
                           (row.get('date', date.today()), row.get('category', 'Sonstiges'), row.get('description', ''), 
                            row.get('amount', 0), row.get('type', 'IST'), row.get('budget_month', date.today().strftime('%Y-%m')), 
                            1 if row.get('is_online') else 0))
            
            if chg["deleted_rows"] or chg["edited_rows"] or chg["added_rows"]:
                st.rerun()
