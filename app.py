import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date

# --- Konfiguration & Setup ---
st.set_page_config(page_title="Cash Stuffing Planer", layout="wide", page_icon="💶")

# Datenbank Pfad
DB_FILE = "/data/budget.db"

# Deutsche Monatsnamen für Anzeige
DE_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}

# Standard-Kategorien für den ersten Start
DEFAULT_CATEGORIES = [
    "Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", 
    "Sonstiges", "Fixkosten", "Kleidung", "Geschenke"
]

def format_euro(val):
    """Hilfsfunktion für deutsche Währungsformatierung"""
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Transaktions-Tabelle
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            category TEXT,
            description TEXT,
            amount REAL,
            type TEXT
        )
    ''')
    
    # 2. Kategorie-Tabelle
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY
        )
    ''')
    
    # Prüfen, ob Kategorien leer sind (Initial-Setup)
    c.execute("SELECT count(*) FROM categories")
    if c.fetchone()[0] == 0:
        for cat in DEFAULT_CATEGORIES:
            c.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
            
    conn.commit()
    conn.close()

def get_categories():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT name FROM categories ORDER BY name ASC", conn)
    conn.close()
    return df['name'].tolist()

def add_category_to_db(new_cat):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO categories (name) VALUES (?)", (new_cat,))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False # Existiert schon
    conn.close()
    return success

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
            df['Jahr'] = df['date'].dt.year
            df['Monat_Jahr'] = df['Monat_Name'] + " " + df['Jahr'].astype(str)
            df['Quartal'] = "Q" + df['date'].dt.quarter.astype(str) + " " + df['Jahr'].astype(str)
        return df
    except:
        return pd.DataFrame()

def save_transaction(dt, cat, desc, amt, typ):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (date, category, description, amount, type) VALUES (?, ?, ?, ?, ?)",
              (dt, cat, desc, amt, typ))
    conn.commit()
    conn.close()

# Initialisierung
try:
    init_db()
except Exception as e:
    st.error(f"Datenbankfehler: {e}")

# --- UI START ---
st.title("💶 Mein Cash Stuffing Planer")

# --- SIDEBAR: Eingabe & Einstellungen ---
st.sidebar.header("Neuer Eintrag")

# Kategorien laden
current_categories = get_categories()

with st.sidebar.form("entry_form", clear_on_submit=True):
    date_input = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
    type_input = st.selectbox("Typ", ["SOLL (Budget)", "IST (Ausgabe)"])
    
    # Dynamisches Dropdown aus DB
    if not current_categories:
        st.warning("Keine Kategorien vorhanden. Bitte unten anlegen!")
        category_input = st.text_input("Kategorie (Fallback)")
    else:
        category_input = st.selectbox("Kategorie", current_categories)
        
    desc_input = st.text_input("Beschreibung (Optional)")
    amount_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
    
    submitted = st.form_submit_button("Speichern")
    if submitted:
        db_type = "SOLL" if "SOLL" in type_input else "IST"
        save_transaction(date_input, category_input, desc_input, amount_input, db_type)
        st.success("Gespeichert!")
        st.rerun()

st.sidebar.markdown("---")

# --- SIDEBAR: Kategorien Management ---
with st.sidebar.expander("⚙️ Kategorien verwalten"):
    st.write("Neue Kategorie hinzufügen:")
    new_cat_name = st.text_input("Name der Kategorie", key="new_cat_input")
    if st.button("Hinzufügen"):
        if new_cat_name:
            if add_category_to_db(new_cat_name):
                st.success(f"'{new_cat_name}' hinzugefügt!")
                st.rerun()
            else:
                st.error("Existiert bereits.")
    
    st.markdown("---")
    st.write("Kategorie löschen:")
    del_cat_name = st.selectbox("Löschen auswählen", current_categories, key="del_cat_select")
    if st.button("Löschen"):
        if del_cat_name:
            delete_category_from_db(del_cat_name)
            st.warning(f"'{del_cat_name}' gelöscht!")
            st.rerun()

# --- HAUPTBEREICH ---
df = load_data()

if df.empty:
    st.info("Willkommen! Noch keine Daten vorhanden. Bitte links Einträge hinzufügen.")
else:
    tab1, tab2, tab3 = st.tabs(["📅 Monatsübersicht", "📊 Trends & Verlauf", "⚖️ Vergleichsrechner"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        
        df['sort_key'] = df['date'].dt.year * 100 + df['date'].dt.month
        month_options = df[['Monat_Jahr', 'sort_key']].drop_duplicates().sort_values('sort_key', ascending=False)
        
        if month_options.empty:
            st.write("Keine Daten.")
        else:
            selected_month_str = st.selectbox("Monat auswählen", month_options['Monat_Jahr'].unique())
            
            df_month = df[df['Monat_Jahr'] == selected_month_str].copy()
            
            pivot = df_month.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in pivot.columns: pivot['SOLL'] = 0.0
            if 'IST' not in pivot.columns: pivot['IST'] = 0.0
            
            pivot['Verfügbar'] = pivot['SOLL'] - pivot['IST']
            pivot['Genutzt %'] = (pivot['IST'] / pivot['SOLL'] * 100).fillna(0)
            
            col1, col2, col3 = st.columns(3)
            total_soll = pivot['SOLL'].sum()
            total_ist = pivot['IST'].sum()
            col1.metric("Gesamt Budget", format_euro(total_soll))
            col2.metric("Gesamt Ausgaben", format_euro(total_ist))
            col3.metric("Restbetrag", format_euro(total_soll - total_ist), delta_color="normal")
            
            st.dataframe(
                pivot.style
                .format("{:.2f} €", subset=['SOLL', 'IST', 'Verfügbar'])
                .format("{:.1f} %", subset=['Genutzt %'])
                .background_gradient(cmap="RdYlGn_r", subset=['Genutzt %'], vmin=0, vmax=120),
                use_container_width=True
            )
            
            with st.expander("Einzelbuchungen anzeigen"):
                display_cols = ['date', 'category', 'description', 'amount', 'type']
                st.dataframe(
                    df_month[display_cols].sort_values(by='date', ascending=False)
                    .style.format({"date": lambda t: t.strftime("%d.%m.%Y"), "amount": "{:.2f} €"}),
                    hide_index=True,
                    use_container_width=True
                )

    # --- TAB 2: Trends ---
    with tab2:
        st.subheader("Verlauf über die Zeit")
        
        view_mode = st.radio("Gruppierung", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True)
        
        if view_mode == "Monatlich":
            agg = df.groupby(['sort_key', 'Monat_Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            agg = agg.reset_index().set_index('Monat_Jahr').sort_values('sort_key')
            chart_data = agg[['SOLL', 'IST']] if 'SOLL' in agg and 'IST' in agg else agg
        elif view_mode == "Quartalsweise":
            agg = df.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0)
            chart_data = agg
        else:
            agg = df.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            chart_data = agg

        st.bar_chart(chart_data)
        
        st.subheader("Ausgaben nach Kategorie (Total)")
        df_ist = df[df['type'] == 'IST']
        if not df_ist.empty:
            cat_agg = df_ist.groupby('category')['amount'].sum().sort_values(ascending=False)
            st.bar_chart(cat_agg)
        else:
            st.info("Keine Ausgabendaten vorhanden.")

    # --- TAB 3: Vergleichsrechner ---
    with tab3:
        st.subheader("📊 Periodenvergleich")
        
        all_periods = []
        all_periods += [f"Monat: {x}" for x in df['Monat_Jahr'].unique()]
        all_periods += [f"Quartal: {x}" for x in df['Quartal'].unique()]
        all_periods += [f"Jahr: {x}" for x in df['Jahr'].unique()]
        
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            p1_sel = st.selectbox("Zeitraum A (Basis)", all_periods, index=0 if len(all_periods) > 0 else None)
        with col_v2:
            def_idx = 1 if len(all_periods) > 1 else 0
            p2_sel = st.selectbox("Zeitraum B (Vergleich)", all_periods, index=def_idx)

        if p1_sel and p2_sel:
            def filter_period(selection):
                type_, val = selection.split(": ")
                if type_ == "Monat":
                    return df[df['Monat_Jahr'] == val]
                elif type_ == "Quartal":
                    return df[df['Quartal'] == val]
                elif type_ == "Jahr":
                    return df[df['Jahr'].astype(str) == val]
                return pd.DataFrame()

            df_a = filter_period(p1_sel)
            df_b = filter_period(p2_sel)
            
            def get_cat_sums(dframe):
                return dframe[dframe['type'] == 'IST'].groupby('category')['amount'].sum()

            sum_a = get_cat_sums(df_a)
            sum_b = get_cat_sums(df_b)
            
            comp_df = pd.DataFrame({'Basis (€)': sum_a, 'Vergleich (€)': sum_b}).fillna(0)
            comp_df['Differenz (€)'] = comp_df['Basis (€)'] - comp_df['Vergleich (€)']
            
            def calc_pct(row):
                if row['Vergleich (€)'] == 0:
                    return 100.0 if row['Basis (€)'] > 0 else 0.0
                return (row['Differenz (€)'] / row['Vergleich (€)']) * 100
                
            comp_df['Veränderung %'] = comp_df.apply(calc_pct, axis=1)
            
            total_row = pd.DataFrame({
                'Basis (€)': [comp_df['Basis (€)'].sum()],
                'Vergleich (€)': [comp_df['Vergleich (€)'].sum()],
                'Differenz (€)': [comp_df['Basis (€)'].sum() - comp_df['Vergleich (€)'].sum()]
            }, index=['GESAMT'])
            total_row['Veränderung %'] = total_row.apply(calc_pct, axis=1)
            
            comp_df = pd.concat([comp_df, total_row])

            st.write(f"Vergleich: **{p1_sel}** vs. **{p2_sel}**")
            
            def style_negative_red_positive_green(val):
                if val == 0: return 'color: black'
                color = 'red' if val > 0 else 'green'
                return f'color: {color}; font-weight: bold'

            st.dataframe(
                comp_df.style
                .format("{:.2f} €", subset=['Basis (€)', 'Vergleich (€)', 'Differenz (€)'])
                .format("{:+.1f} %", subset=['Veränderung %'])
                .applymap(style_negative_red_positive_green, subset=['Differenz (€)', 'Veränderung %']),
                use_container_width=True
            )
