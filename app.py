import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go

# --- Konfiguration & Setup ---
st.set_page_config(page_title="Cash Stuffing Planer", layout="wide", page_icon="💶")

# Datenbank Pfad
DB_FILE = "/data/budget.db"

# Deutsche Monatsnamen
DE_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}

# Standard-Kategorien
DEFAULT_CATEGORIES = [
    "Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", 
    "Sonstiges", "Fixkosten", "Kleidung", "Geschenke", "Notgroschen"
]

PRIO_OPTIONS = ["A - Hoch", "B - Mittel", "C - Niedrig", "Standard"]

def format_euro(val):
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Transaktionen
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            category TEXT,
            description TEXT,
            amount REAL,
            type TEXT,
            budget_month TEXT,
            is_online INTEGER DEFAULT 0
        )
    ''')
    
    # Migration Check (falls User von alter Version kommt)
    try: c.execute("SELECT is_online FROM transactions LIMIT 1")
    except: c.execute("ALTER TABLE transactions ADD COLUMN is_online INTEGER DEFAULT 0")

    # 2. Kategorien
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY,
            priority TEXT DEFAULT 'Standard',
            target_amount REAL DEFAULT 0.0,
            due_date TEXT,
            notes TEXT
        )
    ''')
    
    # Initiale Kategorien
    c.execute("SELECT count(*) FROM categories")
    if c.fetchone()[0] == 0:
        for cat in DEFAULT_CATEGORIES:
            c.execute("INSERT OR IGNORE INTO categories (name, priority) VALUES (?, ?)", (cat, "Standard"))
            
    conn.commit()
    conn.close()

def get_categories_df():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM categories ORDER BY name ASC", conn)
    conn.close()
    return df

def get_categories_list():
    df = get_categories_df()
    return df['name'].tolist()

def add_category_to_db(new_cat, prio):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO categories (name, priority) VALUES (?, ?)", (new_cat, prio))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def update_category_priority(cat_name, new_prio):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE categories SET priority = ? WHERE name = ?", (new_prio, cat_name))
    conn.commit()
    conn.close()

def delete_category_from_db(cat_to_del):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM categories WHERE name = ?", (cat_to_del,))
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_FILE)
    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df['Monat_Name'] = df['date'].dt.month.map(DE_MONTHS)
            df['Monat_Num'] = df['date'].dt.month
            df['Jahr'] = df['date'].dt.year
            df['Quartal'] = "Q" + df['date'].dt.quarter.astype(str) + " " + df['Jahr'].astype(str)
            
            df['budget_month'] = df['budget_month'].fillna(df['date'].dt.strftime('%Y-%m'))
            df['is_online'] = df['is_online'].fillna(0).astype(int)
            
            def get_analysis_month(row):
                if row['type'] == 'SOLL':
                    try:
                        y, m = map(int, row['budget_month'].split('-'))
                        return f"{DE_MONTHS[m]} {y}"
                    except:
                        return f"{DE_MONTHS[row['date'].month]} {row['date'].year}"
                else:
                    return f"{DE_MONTHS[row['date'].month]} {row['date'].year}"

            df['Analyse_Monat'] = df.apply(get_analysis_month, axis=1)
            
            def get_sort_key(row):
                if row['type'] == 'SOLL':
                     try:
                        parts = row['budget_month'].split('-')
                        return int(parts[0]) * 100 + int(parts[1])
                     except:
                        return row['date'].year * 100 + row['date'].month
                else:
                    return row['date'].year * 100 + row['date'].month
            
            df['sort_key_month'] = df.apply(get_sort_key, axis=1)

        return df
    except Exception as e:
        return pd.DataFrame()

def save_transaction(dt, cat, desc, amt, typ, budget_mon=None, is_online=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if not budget_mon:
        budget_mon = dt.strftime("%Y-%m")
    online_int = 1 if is_online else 0
    c.execute("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (dt, cat, desc, amt, typ, budget_mon, online_int))
    conn.commit()
    conn.close()

def perform_transfer(date_val, cat_from, cat_to, amount):
    save_transaction(date_val, cat_from, f"Umbuchung zu {cat_to}", -amount, "SOLL", date_val.strftime("%Y-%m"))
    save_transaction(date_val, cat_to, f"Umbuchung von {cat_from}", amount, "SOLL", date_val.strftime("%Y-%m"))

def perform_bank_deposit(date_val, amount):
    # Spezieller Typ für Bankeinzahlung
    # Kategorie ist fix "Back to Bank"
    save_transaction(date_val, "Back to Bank", "Einzahlung auf Konto", amount, "BANK_DEPOSIT", date_val.strftime("%Y-%m"))

# Initialisierung
try:
    init_db()
except Exception as e:
    st.error(f"Datenbankfehler: {e}")

# --- UI START ---
st.title("💶 Mein Cash Stuffing Planer")

# --- SIDEBAR ---
# Jetzt 4 Tabs
sb_tab1, sb_tab2, sb_tab3, sb_tab4 = st.sidebar.tabs(["📝 Einzeln", "💰 Verteiler", "💸 Umbuchung", "🏦 Bank"])
current_cats_df = get_categories_df()
current_categories = current_cats_df['name'].tolist()

# TAB 1: EINZEL BUCHUNG
with sb_tab1:
    with st.form("entry_form", clear_on_submit=True):
        date_input = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        type_input = st.selectbox("Typ", ["IST (Ausgabe)", "SOLL (Budget einzahlen)"])
        
        budget_target = None
        if "SOLL" in type_input:
            st.caption("Ziel-Monat:")
            today = date.today()
            this_lbl = f"{DE_MONTHS[today.month]} {today.year}"
            next_m = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            next_lbl = f"{DE_MONTHS[next_m.month]} {next_m.year}"
            choice = st.radio("M", [this_lbl, next_lbl], horizontal=True, label_visibility="collapsed")
            budget_target = today.strftime("%Y-%m") if choice == this_lbl else next_m.strftime("%Y-%m")
        
        if not current_categories:
            st.warning("Keine Kategorien!")
            category_input = st.text_input("Kategorie")
        else:
            category_input = st.selectbox("Kategorie", current_categories)
            
        desc_input = st.text_input("Info (Opt)")
        amount_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
        
        is_online_input = False
        if "IST" in type_input:
            is_online_input = st.checkbox("💳 Online / Karte bezahlt?", help="Haken setzen, wenn Geld vom Konto ging.")
        
        if st.form_submit_button("Speichern"):
            db_type = "SOLL" if "SOLL" in type_input else "IST"
            save_transaction(date_input, category_input, desc_input, amount_input, db_type, budget_target, is_online_input)
            st.success("Gespeichert!")
            st.rerun()

# TAB 2: BULK VERTEILER
with sb_tab2:
    st.write("Budget Verteiler")
    bulk_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY", key="bulk_date")
    today = date.today()
    this_lbl = f"{DE_MONTHS[today.month]} {today.year}"
    next_m = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    next_lbl = f"{DE_MONTHS[next_m.month]} {next_m.year}"
    bulk_choice = st.radio("Für Monat:", [this_lbl, next_lbl], horizontal=True, key="bulk_month_choice")
    bulk_target_month = today.strftime("%Y-%m") if bulk_choice == this_lbl else next_m.strftime("%Y-%m")
    
    if "bulk_df" not in st.session_state or len(st.session_state.bulk_df) != len(current_categories):
        st.session_state.bulk_df = pd.DataFrame({
            "Kategorie": current_categories,
            "Betrag": [0.0] * len(current_categories)
        })

    col_cfg = {
        "Kategorie": st.column_config.TextColumn("Kategorie", disabled=True),
        "Betrag": st.column_config.NumberColumn("Betrag (€)", min_value=0, format="%.2f €")
    }
    
    edited_bulk = st.data_editor(st.session_state.bulk_df, column_config=col_cfg, hide_index=True, use_container_width=True, key="bulk_editor", num_rows="fixed")
    
    total_bulk = edited_bulk["Betrag"].sum()
    st.metric("Summe", format_euro(total_bulk))
    
    if st.button("Buchen"):
        if total_bulk == 0: st.warning("Summe ist 0.")
        else:
            c = 0
            for index, row in edited_bulk.iterrows():
                if row["Betrag"] > 0:
                    save_transaction(bulk_date, row["Kategorie"], "Budget Verteiler", row["Betrag"], "SOLL", bulk_target_month)
                    c += 1
            st.session_state.bulk_df = pd.DataFrame({"Kategorie": current_categories, "Betrag": [0.0]*len(current_categories)})
            st.success(f"{c} Budgets gebucht!")
            st.rerun()

# TAB 3: UMBUCHUNG
with sb_tab3:
    st.write("Umbuchung")
    with st.form("transfer_form", clear_on_submit=True):
        t_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        if len(current_categories) >= 2:
            c1, c2 = st.columns(2)
            cat_from = c1.selectbox("Von", current_categories, index=0)
            def_idx = 1
            for i, c in enumerate(current_categories):
                if "Spar" in c or "Notgroschen" in c:
                    if c != cat_from:
                        def_idx = i; break
            cat_to = c2.selectbox("Nach", current_categories, index=def_idx)
            t_amt = st.number_input("Betrag", min_value=0.0, format="%.2f", key="t_amt")
            if st.form_submit_button("Umbuchen"):
                if cat_from == cat_to: st.error("Identisch.")
                else:
                    perform_transfer(t_date, cat_from, cat_to, t_amt)
                    st.success("Erledigt.")
                    st.rerun()
        else: st.warning("Zu wenig Kategorien.")

# TAB 4: BACK TO BANK (NEU)
with sb_tab4:
    st.write("🏦 Back to Bank")
    st.caption("Verwalte den Umschlag für Online-Zahlungen.")
    
    # Daten für Berechnung laden (Alle Zeiten)
    # Wir brauchen df (wird unten geladen, aber wir machen hier eine schnelle Query für die Sidebar Performance)
    # Oder wir nutzen df von unten, aber Streamlit läuft script-based von oben nach unten.
    # Wir machen eine kleine Query:
    conn = sqlite3.connect(DB_FILE)
    
    # 1. Summe aller Online Ausgaben (IST & is_online=1)
    online_sum = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='IST' AND is_online=1", conn).iloc[0,0]
    if not online_sum: online_sum = 0.0
    
    # 2. Summe aller Einzahlungen (BANK_DEPOSIT)
    deposit_sum = pd.read_sql_query("SELECT SUM(amount) FROM transactions WHERE type='BANK_DEPOSIT'", conn).iloc[0,0]
    if not deposit_sum: deposit_sum = 0.0
    conn.close()
    
    b2b_balance = online_sum - deposit_sum
    
    # Anzeige
    st.metric("Im Umschlag", format_euro(b2b_balance))
    
    if b2b_balance > 0.01:
        st.write("Geld am Automaten eingezahlt?")
        with st.form("deposit_form"):
            dep_date = st.date_input("Datum", date.today())
            dep_amount = st.number_input("Betrag", value=b2b_balance, min_value=0.0, max_value=b2b_balance, format="%.2f")
            if st.form_submit_button("Einzahlung buchen"):
                perform_bank_deposit(dep_date, dep_amount)
                st.success("Gebucht!")
                st.rerun()
    elif b2b_balance < -0.01:
        st.error("Negativer Betrag! Du hast mehr eingezahlt als online ausgegeben.")
    else:
        st.info("Umschlag ist leer. Alles ausgeglichen.")


st.sidebar.markdown("---")

# KATEGORIE VERWALTUNG
with st.sidebar.expander("⚙️ Kategorien & Prioritäten"):
    st.caption("Neue Kategorie")
    c_new1, c_new2 = st.columns([2, 1])
    with c_new1: new_cat_name = st.text_input("Name", key="new_cat_input", label_visibility="collapsed", placeholder="Name")
    with c_new2: new_cat_prio = st.selectbox("Prio", PRIO_OPTIONS, index=3, label_visibility="collapsed", key="new_prio_select")
    
    if st.button("Hinzufügen"):
        if new_cat_name:
            if add_category_to_db(new_cat_name, new_cat_prio):
                if "bulk_df" in st.session_state: del st.session_state.bulk_df
                st.rerun()
    
    st.markdown("---")
    st.caption("Prio ändern / Löschen")
    edit_cat = st.selectbox("Kategorie wählen", current_categories, key="edit_cat_sel")
    if edit_cat:
        curr_prio = current_cats_df[current_cats_df['name'] == edit_cat]['priority'].iloc[0]
        if not curr_prio: curr_prio = "Standard"
        try: prio_idx = PRIO_OPTIONS.index(curr_prio)
        except: prio_idx = 3
            
        new_prio_edit = st.selectbox("Priorität ändern", PRIO_OPTIONS, index=prio_idx, key="edit_prio_sel")
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("Speichern"):
                update_category_priority(edit_cat, new_prio_edit)
                st.success("Gespeichert!")
                st.rerun()
        with c_btn2:
            if st.button("🗑 Löschen", type="primary"):
                delete_category_from_db(edit_cat)
                if "bulk_df" in st.session_state: del st.session_state.bulk_df
                st.rerun()

# --- HAUPTBEREICH ---
df = load_data()

if df.empty and not current_categories:
    st.info("Bitte erstelle erste Einträge in der Sidebar.")
else:
    tab1, tab6, tab2, tab3, tab4, tab5 = st.tabs(["📅 Monatsübersicht", "🎯 Sinking Funds", "📈 Verlauf", "📊 Trends", "⚖️ Vergleich", "📝 Editor"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        col_sel1, col_sel2 = st.columns([1, 2])
        month_options = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
        
        if not month_options.empty:
            with col_sel1:
                selected_month_label = st.selectbox("Monat auswählen", month_options['Analyse_Monat'].unique())
            with col_sel2:
                sel_categories = st.multiselect("Filter", current_categories, default=current_categories)
            
            current_sort_key = month_options[month_options['Analyse_Monat'] == selected_month_label]['sort_key_month'].iloc[0]
            
            # WICHTIG: BANK_DEPOSIT aus der normalen Übersicht filtern, sonst tauchen sie als Ausgaben/Budgets auf
            # Wir wollen hier nur SOLL und IST sehen
            df_curr = df[(df['sort_key_month'] == current_sort_key) & (df['type'].isin(['SOLL', 'IST']))].copy()
            df_prev = df[(df['sort_key_month'] < current_sort_key) & (df['type'].isin(['SOLL', 'IST']))].copy()
            
            prev_soll = df_prev[df_prev['type'] == 'SOLL'].groupby('category')['amount'].sum()
            prev_ist = df_prev[df_prev['type'] == 'IST'].groupby('category')['amount'].sum()
            carryover = prev_soll.subtract(prev_ist, fill_value=0)
            
            curr_soll = df_curr[df_curr['type'] == 'SOLL'].groupby('category')['amount'].sum()
            curr_ist = df_curr[df_curr['type'] == 'IST'].groupby('category')['amount'].sum()
            
            overview = pd.DataFrame({
                'Übertrag Vormonat': carryover,
                'Budget (Neu)': curr_soll,
                'Ausgaben (IST)': curr_ist
            }).fillna(0)
            
            if sel_categories: overview = overview[overview.index.isin(sel_categories)]
            else: overview = overview[overview.index.isin([])]
            
            overview['Gesamt Verfügbar'] = overview['Übertrag Vormonat'] + overview['Budget (Neu)']
            overview['Rest'] = overview['Gesamt Verfügbar'] - overview['Ausgaben (IST)']
            overview['Genutzt %'] = (overview['Ausgaben (IST)'] / overview['Gesamt Verfügbar'] * 100).fillna(0)
            
            overview = overview.merge(current_cats_df.set_index('name'), left_index=True, right_index=True, how='left')
            overview['priority'] = overview['priority'].fillna("Standard")
            overview = overview.sort_values(by=['priority', 'Gesamt Verfügbar'], ascending=[True, False])
            
            overview = overview.drop(columns=['target_amount', 'due_date', 'notes'], errors='ignore')

            if not overview.empty:
                sum_row = overview.sum(numeric_only=True)
                total_used, total_avail = sum_row['Ausgaben (IST)'], sum_row['Gesamt Verfügbar']
                sum_row['Genutzt %'] = (total_used / total_avail * 100) if total_avail > 0 else 0
                
                sum_df = pd.DataFrame(sum_row).T
                sum_df['priority'] = ""
                sum_df.index = ["∑ GESAMT"]
                
                # B2B Berechnung in der Sidebar gemacht, hier zeigen wir nur Warnung wenn Umschlag voll
                # Wir holen den Wert erneut für die Visualisierung
                # (Einfacher: Wir nutzen die Sidebar Berechnung, aber die Variable ist dort lokal)
                # Wir berechnen es nochmal kurz globaler:
                
                # Wir zeigen in der Info Box einfach den aktuellen B2B Stand (Global)
                # Aber Achtung: Das Dashboard zeigt einen ausgewählten Monat.
                # Der B2B Umschlag ist aber zeitunabhängig (ein Topf).
                # Wir zeigen daher: "In diesem Monat online ausgegeben: X €" UND "Aktuell im Umschlag: Y €"
                
                if sel_categories:
                     month_online = df_curr[(df_curr['type'] == 'IST') & (df_curr['is_online'] == 1) & (df_curr['category'].isin(sel_categories))]['amount'].sum()
                else:
                     month_online = df_curr[(df_curr['type'] == 'IST') & (df_curr['is_online'] == 1)]['amount'].sum()
                
                # Globaler B2B Stand (Wiederholung der Sidebar Logik für Anzeige hier)
                all_online_sum = df[(df['type']=='IST') & (df['is_online']==1)]['amount'].sum()
                all_dep_sum = df[df['type']=='BANK_DEPOSIT']['amount'].sum()
                global_b2b = all_online_sum - all_dep_sum

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Übertrag (Alt)", format_euro(sum_row['Übertrag Vormonat']))
                c2.metric("Frisches Budget", format_euro(sum_row['Budget (Neu)']))
                c3.metric("Ausgaben", format_euro(sum_row['Ausgaben (IST)']))
                c4.metric("Aktueller Rest", format_euro(sum_row['Rest']), delta_color="normal")
                
                # INFO BOX
                if global_b2b > 0:
                    st.info(f"💳 **Back to Bank:** Du hast diesen Monat **{format_euro(month_online)}** online bezahlt. \n\n **Aktueller Umschlag-Inhalt (Gesamt):** {format_euro(global_b2b)} (siehe Sidebar 'Bank').")
                else:
                    st.success("Back to Bank Umschlag ist leer/ausgeglichen.")

                display_df = pd.concat([overview, sum_df])
                
                def highlight_prio(val):
                    if "A -" in str(val): return 'color: #d90429; font-weight: bold'
                    if "B -" in str(val): return 'color: #e36414'
                    if "C -" in str(val): return 'color: #0f4c5c'
                    return ''

                st.dataframe(
                    display_df.style
                    .format("{:.2f} €", subset=['Übertrag Vormonat', 'Budget (Neu)', 'Ausgaben (IST)', 'Gesamt Verfügbar', 'Rest'])
                    .format("{:.1f} %", subset=['Genutzt %'])
                    .bar(subset=['Genutzt %'], color='#ffbd45', vmin=0, vmax=100)
                    .applymap(lambda v: 'color: gray', subset=['Übertrag Vormonat'])
                    .applymap(lambda v: 'font-weight: bold; background-color: #f0f2f6', subset=pd.IndexSlice[display_df.index[-1], :])
                    .applymap(highlight_prio, subset=['priority'])
                    .applymap(lambda v: 'font-weight: bold', subset=['Rest']),
                    use_container_width=True
                )
            else:
                st.info("Kategorien wählen.")

            if sel_categories: df_curr_filtered = df_curr[df_curr['category'].isin(sel_categories)]
            else: df_curr_filtered = pd.DataFrame()
            with st.expander("Einzelbuchungen (Gefiltert)"):
                if not df_curr_filtered.empty:
                    df_curr_filtered['Art'] = df_curr_filtered['is_online'].apply(lambda x: "💳 Online" if x==1 else "💵 Bar")
                    st.dataframe(df_curr_filtered[['date', 'Art', 'category', 'description', 'amount', 'type']].sort_values(by='date', ascending=False).style.format({"date": lambda t: t.strftime("%d.%m.%Y"), "amount": "{:.2f} €"}), hide_index=True, use_container_width=True)

    # --- TAB 6: SINKING FUNDS ---
    with tab6:
        st.subheader("🎯 Sinking Funds Planung")
        st.markdown("Verwalte hier deine Sparziele.")
        
        # Sinking Funds sollen auch nur SOLL und IST beachten, keine Bank Deposits
        df_sf_calc = df[df['type'].isin(['SOLL', 'IST'])].copy()
        
        soll_all = df_sf_calc[df_sf_calc['type'] == 'SOLL'].groupby('category')['amount'].sum()
        ist_all = df_sf_calc[df_sf_calc['type'] == 'IST'].groupby('category')['amount'].sum()
        current_balance = soll_all.subtract(ist_all, fill_value=0)
        
        sf_df = current_cats_df.copy().set_index('name')
        sf_df['due_date'] = pd.to_datetime(sf_df['due_date'], errors='coerce')
        sf_df['Aktuell'] = current_balance
        sf_df['Aktuell'] = sf_df['Aktuell'].fillna(0.0)
        
        today = date.today()
        
        def calc_savings_rate(row):
            target = row['target_amount'] if pd.notnull(row['target_amount']) else 0
            curr = row['Aktuell']
            due_val = row['due_date']
            
            if target <= 0: return 0.0, "Kein Ziel"
            if curr >= target: return 0.0, "✅ Ziel erreicht"
            
            if pd.isnull(due_val): return 0.0, "Kein Datum"
            if hasattr(due_val, "date"): due = due_val.date()
            else: due = due_val

            missing = target - curr
            if due <= today: return missing, "❗ Überfällig"
            
            diff = relativedelta(due, today)
            months_left = diff.years * 12 + diff.months
            if months_left == 0: months_left = 1
            rate = missing / months_left
            return rate, f"{months_left} Monate"

        res = sf_df.apply(calc_savings_rate, axis=1, result_type='expand')
        sf_df['Monatl. Rate'] = res[0]
        sf_df['Status'] = res[1]
        
        sf_df['%'] = (sf_df['Aktuell'] / sf_df['target_amount'] * 100).fillna(0)
        sf_df.loc[sf_df['target_amount'] <= 0, '%'] = 0
        
        sf_df['priority'] = sf_df['priority'].fillna("Standard")
        
        def show_prio_group(prio_label, color_code):
            group_df = sf_df[sf_df['priority'] == prio_label].copy()
            if not group_df.empty:
                st.markdown(f"#### :{color_code}[{prio_label}]")
                col_config = {
                    "priority": None,
                    "Aktuell": st.column_config.NumberColumn("Ist-Stand", format="%.2f €", disabled=True),
                    "target_amount": st.column_config.NumberColumn("Zielbetrag (€)", min_value=0, format="%.2f €", required=True),
                    "due_date": st.column_config.DateColumn("Fällig am", format="DD.MM.YYYY"),
                    "notes": st.column_config.TextColumn("Notizen"),
                    "Monatl. Rate": st.column_config.NumberColumn("Sparrate / Monat", format="%.2f €", disabled=True),
                    "Status": st.column_config.TextColumn("Zeitraum", disabled=True),
                    "%": st.column_config.ProgressColumn("Fortschritt", min_value=0, max_value=100, format="%.0f%%"),
                }
                group_df = group_df.reset_index()
                col_config["name"] = st.column_config.TextColumn("Kategorie", disabled=True)
                
                ed_key = f"sf_editor_{prio_label}"
                edited_sf = st.data_editor(
                    group_df,
                    column_config=col_config,
                    key=ed_key,
                    hide_index=True,
                    use_container_width=True,
                    column_order=["name", "Aktuell", "target_amount", "due_date", "%", "Monatl. Rate", "Status", "notes"]
                )
                
                if ed_key in st.session_state:
                    changes = st.session_state[ed_key]
                    if changes["edited_rows"]:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        updated = False
                        for idx, row_changes in changes["edited_rows"].items():
                            cat_name = group_df.iloc[idx]['name']
                            curr_target = group_df.iloc[idx]['target_amount']
                            curr_due = group_df.iloc[idx]['due_date']
                            curr_note = group_df.iloc[idx]['notes']
                            new_target = row_changes.get("target_amount", curr_target)
                            new_due = row_changes.get("due_date", curr_due)
                            new_note = row_changes.get("notes", curr_note)
                            if isinstance(new_due, (date, datetime.datetime)):
                                new_due = new_due.strftime("%Y-%m-%d")
                            elif pd.isnull(new_due):
                                new_due = None
                            c.execute("UPDATE categories SET target_amount = ?, due_date = ?, notes = ? WHERE name = ?", 
                                      (new_target, new_due, new_note, cat_name))
                            updated = True
                        conn.commit()
                        conn.close()
                        if updated: st.rerun()

        show_prio_group("A - Hoch", "red")
        show_prio_group("B - Mittel", "orange")
        show_prio_group("C - Niedrig", "blue")
        show_prio_group("Standard", "grey")

    # --- TAB 2-5 ---
    # Hier filtern wir auch BANK_DEPOSIT raus, damit es Charts nicht verfälscht
    df_charts = df[df['type'].isin(['SOLL', 'IST'])].copy()

    with tab2:
        st.subheader("📈 Verlauf")
        mode = st.radio("Modus", ["Monate (Tag 1-31)", "Jahre (Jan-Dez)", "Quartale"], horizontal=True)
        cat_options = ["Alle"] + sorted(current_categories)
        sel_cat = st.selectbox("Kategorie", cat_options)
        df_c = df_charts[df_charts['type'] == 'IST'].copy()
        if sel_cat != "Alle": df_c = df_c[df_c['category'] == sel_cat]
        x_vals, y_a, y_b, n_a, n_b = [], [], [], "", ""
        if "Monate" in mode:
            opts = df_charts[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            all_m = opts['Analyse_Monat'].unique()
            if len(all_m) >= 1:
                c1, c2 = st.columns(2)
                with c1: n_a = st.selectbox("A", all_m, index=0)
                with c2: n_b = st.selectbox("B", all_m, index=1 if len(all_m)>1 else 0)
                def get_d(dframe, m_lbl):
                    d = dframe[dframe['Analyse_Monat'] == m_lbl]
                    return d.groupby(d['date'].dt.day)['amount'].sum().reindex(range(1, 32), fill_value=0)
                y_a, y_b = get_d(df_c, n_a), get_d(df_c, n_b)
                x_vals = list(range(1, 32))
        elif "Jahre" in mode:
            ys = sorted(df_charts['Jahr'].unique())
            if ys:
                idx = len(ys)-1
                c1, c2 = st.columns(2)
                with c1: n_a = st.selectbox("A", ys, index=idx)
                with c2: n_b = st.selectbox("B", ys, index=idx-1 if idx>0 else idx)
                def get_y(dframe, y):
                    return dframe[dframe['Jahr']==y].groupby('Monat_Num')['amount'].sum().reindex(range(1,13), fill_value=0)
                y_a, y_b = get_y(df_c, n_a), get_y(df_c, n_b)
                x_vals = [DE_MONTHS[i] for i in range(1,13)]
                n_a, n_b = str(n_a), str(n_b)
        else:
            qs = sorted(df_charts['Quartal'].unique(), reverse=True)
            if qs:
                c1, c2 = st.columns(2)
                with c1: n_a = st.selectbox("A", qs, index=0)
                with c2: n_b = st.selectbox("B", qs, index=1 if len(qs)>1 else 0)
                def get_q(dframe, q):
                    d = dframe[dframe['Quartal']==q].copy()
                    if d.empty: return pd.Series([0,0,0], index=[1,2,3])
                    d['rm'] = (d['date'].dt.month-1)%3+1
                    return d.groupby('rm')['amount'].sum().reindex(range(1,4), fill_value=0)
                y_a, y_b = get_q(df_c, n_a), get_q(df_c, n_b)
                x_vals = ["M1", "M2", "M3"]
        if len(y_a) > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x_vals, y=y_a.values, mode='lines+markers', name=n_a, line=dict(color='#0055ff', width=3), fill='tozeroy', fillcolor='rgba(0, 85, 255, 0.1)'))
            fig.add_trace(go.Scatter(x=x_vals, y=y_b.values, mode='lines+markers', name=n_b, line=dict(color='gray', width=2, dash='dot')))
            fig.update_layout(title=f"{sel_cat}: {n_a} vs {n_b}", yaxis_title="€", template="plotly_white", hovermode="x unified", legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01), margin=dict(l=20, r=20, t=40, b=20))
            if "Monate" in mode: fig.update_xaxes(title="Tag", tickmode='linear', tick0=1, dtick=1)
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("Balken-Übersicht")
        vm = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True, key="tr_rad")
        if vm == "Monatlich":
            agg = df_charts.groupby(['sort_key_month', 'Analyse_Monat', 'type'])['amount'].sum().unstack(fill_value=0)
            agg = agg.reset_index().sort_values('sort_key_month').set_index('Analyse_Monat')
            cols = [c for c in ['SOLL', 'IST'] if c in agg.columns]
            st.bar_chart(agg[cols])
        elif vm == "Quartalsweise": st.bar_chart(df_charts.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0))
        else: st.bar_chart(df_charts.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0))

    with tab4:
        st.subheader("📊 Periodenvergleich")
        aps = [f"M: {x}" for x in df['Analyse_Monat'].unique()] + [f"Q: {x}" for x in df['Quartal'].unique()] + [f"J: {x}" for x in df['Jahr'].unique()]
        if aps:
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Basis", aps, key="p1")
            p2 = c2.selectbox("Vgl", aps, key="p2", index=1 if len(aps)>1 else 0)
            if p1 and p2:
                def fp(sel):
                    t, v = sel.split(": ")
                    if t=="M": return df_charts[df_charts['Analyse_Monat']==v]
                    if t=="Q": return df_charts[df_charts['Quartal']==v]
                    if t=="J": return df_charts[df_charts['Jahr'].astype(str)==v]
                    return pd.DataFrame()
                d_a, d_b = fp(p1), fp(p2)
                if not d_a.empty and not d_b.empty:
                    sa, sb = d_a[d_a['type']=='IST'].groupby('category')['amount'].sum(), d_b[d_b['type']=='IST'].groupby('category')['amount'].sum()
                    cp = pd.DataFrame({'Basis': sa, 'Vgl': sb}).fillna(0)
                    cp['Diff'], cp['%'] = cp['Basis']-cp['Vgl'], cp.apply(lambda r: (r['Basis']-r['Vgl'])/r['Vgl']*100 if r['Vgl']!=0 else (100 if r['Basis']>0 else 0), axis=1)
                    st.dataframe(cp.style.format("{:.2f} €", subset=['Basis','Vgl','Diff']).format("{:+.1f} %", subset=['%']).applymap(lambda v: f'color: {"red" if v>0 else "green"}; font-weight: bold' if v!=0 else 'color:black', subset=['Diff', '%']), use_container_width=True)

    with tab5:
        st.subheader("📝 Daten korrigieren")
        # Im Editor zeigen wir ALLES, auch BANK_DEPOSIT, damit man es korrigieren kann
        df_ed = df.sort_values(by=['date', 'id'], ascending=[False, False]).copy()
        col_conf = {
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
            "category": st.column_config.SelectboxColumn("Kategorie", options=current_categories + ["Back to Bank"], required=True),
            "type": st.column_config.SelectboxColumn("Typ", options=["SOLL", "IST", "BANK_DEPOSIT"], required=True),
            "amount": st.column_config.NumberColumn("Betrag (€)", format="%.2f €", min_value=0),
            "budget_month": st.column_config.TextColumn("Budget Monat (YYYY-MM)"),
            "is_online": st.column_config.CheckboxColumn("Online/Karte?", default=False),
            "description": st.column_config.TextColumn("Info"),
            "Analyse_Monat": None, "Monat_Name": None, "Monat_Num": None, "Jahr": None, "Quartal": None, "sort_key_month": None
        }
        edited = st.data_editor(df_ed, key="trans_ed", column_config=col_conf, num_rows="dynamic", use_container_width=True, hide_index=True)
        if st.session_state["trans_ed"]:
            chg = st.session_state["trans_ed"]
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            mod = False
            if chg["deleted_rows"]:
                for idx in chg["deleted_rows"]:
                    if idx in df_ed.index: 
                       try:
                           row_id = df_ed.iloc[idx]['id']
                           c.execute("DELETE FROM transactions WHERE id = ?", (int(row_id),))
                       except: pass
                mod = True
            if chg["edited_rows"]:
                for idx, row_chg in chg["edited_rows"].items():
                    rid = df_ed.iloc[idx]['id']
                    for k, v in row_chg.items():
                        c.execute(f"UPDATE transactions SET {k} = ? WHERE id = ?", (v, int(rid)))
                mod = True
            if chg["added_rows"]:
                for r in chg["added_rows"]:
                    dt = r.get("date", date.today())
                    bm = r.get("budget_month", None)
                    if not bm and isinstance(dt, (date, datetime.datetime)): bm = dt.strftime("%Y-%m")
                    elif not bm: bm = date.today().strftime("%Y-%m")
                    online_val = 1 if r.get("is_online", False) else 0
                    c.execute("INSERT INTO transactions (date, category, description, amount, type, budget_month, is_online) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (dt, r.get("category", "Sonstiges"), r.get("description", ""), r.get("amount", 0.0), r.get("type", "IST"), bm, online_val))
                mod = True
            conn.commit()
            conn.close()
            if mod:
                st.success("Gespeichert!")
                st.rerun()
