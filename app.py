import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date

# --- Kofiguration & Setup ---
st.set_page_config(page_title="Cash Stuffing Budget", layout="wide", page_icon="💶")

# Datenbank Pfad im Docker Container
DB_FILE = "/data/budget.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
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
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_FILE)
    # Fehlerbehandlung, falls DB noch leer ist oder gelockt
    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
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

# Initialisiere DB beim Start
try:
    init_db()
except Exception as e:
    st.error(f"Datenbankfehler: {e}. Prüfe ob der Ordner /data beschreibbar ist.")

# --- UI START ---
st.title("💶 Mein Cash Stuffing Planer")

# Sidebar
st.sidebar.header("Neuer Eintrag")
with st.sidebar.form("entry_form", clear_on_submit=True):
    date_input = st.date_input("Datum", date.today())
    type_input = st.selectbox("Typ", ["SOLL (Budget)", "IST (Ausgabe)"])
    category_input = st.selectbox("Kategorie", ["Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", "Sonstiges", "Fixkosten"])
    desc_input = st.text_input("Beschreibung (Optional)")
    amount_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
    
    submitted = st.form_submit_button("Speichern")
    if submitted:
        db_type = "SOLL" if "SOLL" in type_input else "IST"
        save_transaction(date_input, category_input, desc_input, amount_input, db_type)
        st.success("Gespeichert!")
        st.rerun()

df = load_data()

if df.empty:
    st.info("Willkommen! Noch keine Daten vorhanden. Bitte links Einträge hinzufügen.")
else:
    tab1, tab2 = st.tabs(["📅 Monatsübersicht", "📊 Dashboard & Statistik"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        df['year_month'] = df['date'].dt.to_period('M')
        available_months = sorted(df['year_month'].unique(), reverse=True)
        
        if not available_months:
            st.write("Keine Daten.")
        else:
            month_tabs = st.tabs([str(m) for m in available_months[:6]])
            for i, period in enumerate(available_months[:6]):
                with month_tabs[i]:
                    mask = (df['year_month'] == period)
                    df_month = df.loc[mask]
                    
                    pivot = df_month.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
                    if 'SOLL' not in pivot.columns: pivot['SOLL'] = 0.0
                    if 'IST' not in pivot.columns: pivot['IST'] = 0.0
                    
                    pivot['Verfügbar'] = pivot['SOLL'] - pivot['IST']
                    pivot['Genutzt %'] = (pivot['IST'] / pivot['SOLL'] * 100).fillna(0).round(1)
                    
                    col1, col2, col3 = st.columns(3)
                    total_soll = pivot['SOLL'].sum()
                    total_ist = pivot['IST'].sum()
                    col1.metric("Gesamt Budget", f"{total_soll:.2f} €")
                    col2.metric("Gesamt Ausgaben", f"{total_ist:.2f} €")
                    col3.metric("Restbetrag", f"{total_soll - total_ist:.2f} €", delta_color="normal")
                    
                    st.dataframe(pivot.style.format("{:.2f} €", subset=['SOLL', 'IST', 'Verfügbar'])
                                 .format("{:.1f} %", subset=['Genutzt %']), use_container_width=True)
                    
                    st.caption("Letzte Buchungen:")
                    st.dataframe(df_month[['date', 'category', 'description', 'amount', 'type']].sort_values(by='date', ascending=False), hide_index=True)

    # --- TAB 2: Dashboard ---
    with tab2:
        st.subheader("Analyse & Filter")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            years = sorted(df['date'].dt.year.unique(), reverse=True)
            selected_year = st.selectbox("Jahr auswählen", years) if years else st.write("Keine Jahre")
        
        with col_f2:
            view_mode = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True)

        if years:
            df_filtered = df[df['date'].dt.year == selected_year].copy()
            if view_mode == "Monatlich":
                group_col = df_filtered['date'].dt.month_name()
            elif view_mode == "Quartalsweise":
                group_col = "Q" + df_filtered['date'].dt.quarter.astype(str)
            else:
                group_col = df_filtered['date'].dt.year.astype(str)

            df_filtered['Zeitraum'] = group_col
            agg = df_filtered.groupby(['Zeitraum', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in agg.columns: agg['SOLL'] = 0
            if 'IST' not in agg.columns: agg['IST'] = 0
            
            st.bar_chart(agg[['SOLL', 'IST']])
            
            st.subheader("Kategorie Performance")
            cat_agg = df_filtered.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in cat_agg.columns: cat_agg['SOLL'] = 0
            if 'IST' not in cat_agg.columns: cat_agg['IST'] = 0
            cat_agg['Abweichung %'] = ((cat_agg['IST'] - cat_agg['SOLL']) / cat_agg['SOLL'] * 100).fillna(0).round(1)
            st.dataframe(cat_agg.style.background_gradient(cmap="RdYlGn_r", subset=['Abweichung %']), use_container_width=True)
