import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date

# --- Konfiguration & Setup ---
st.set_page_config(page_title="Cash Stuffing Planer", layout="wide", page_icon="💶")

# Datenbank Pfad
DB_FILE = "/data/budget.db"

# Deutsche Monatsnamen für Anzeige (Docker-safe ohne System-Locales)
DE_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
}

def format_euro(val):
    """Hilfsfunktion für deutsche Währungsformatierung"""
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

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
    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            # Hilfsspalten für Zeiträume
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

# Sidebar
st.sidebar.header("Neuer Eintrag")
with st.sidebar.form("entry_form", clear_on_submit=True):
    # format="DD.MM.YYYY" erzwingt deutsche Eingabeanzeige
    date_input = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
    type_input = st.selectbox("Typ", ["SOLL (Budget)", "IST (Ausgabe)"])
    category_input = st.selectbox("Kategorie", ["Lebensmittel", "Miete", "Sparen", "Freizeit", "Transport", "Sonstiges", "Fixkosten", "Kleidung", "Geschenke"])
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
    # Drei Tabs für die Logik
    tab1, tab2, tab3 = st.tabs(["📅 Monatsübersicht", "📊 Trends & Verlauf", "⚖️ Vergleichsrechner"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        
        # Sortierung für Auswahlbox: Neueste Monate zuerst
        # Wir erstellen einen Sortierschlüssel YYYYMM
        df['sort_key'] = df['date'].dt.year * 100 + df['date'].dt.month
        month_options = df[['Monat_Jahr', 'sort_key']].drop_duplicates().sort_values('sort_key', ascending=False)
        
        if month_options.empty:
            st.write("Keine Daten.")
        else:
            selected_month_str = st.selectbox("Monat auswählen", month_options['Monat_Jahr'].unique())
            
            # Daten filtern
            df_month = df[df['Monat_Jahr'] == selected_month_str].copy()
            
            # Pivot Tabelle
            pivot = df_month.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in pivot.columns: pivot['SOLL'] = 0.0
            if 'IST' not in pivot.columns: pivot['IST'] = 0.0
            
            pivot['Verfügbar'] = pivot['SOLL'] - pivot['IST']
            pivot['Genutzt %'] = (pivot['IST'] / pivot['SOLL'] * 100).fillna(0)
            
            # Metriken (KPIs)
            col1, col2, col3 = st.columns(3)
            total_soll = pivot['SOLL'].sum()
            total_ist = pivot['IST'].sum()
            col1.metric("Gesamt Budget", format_euro(total_soll))
            col2.metric("Gesamt Ausgaben", format_euro(total_ist))
            col3.metric("Restbetrag", format_euro(total_soll - total_ist), delta_color="normal")
            
            # Tabelle aufhübschen
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
            # Sortierung sicherstellen
            agg = df.groupby(['sort_key', 'Monat_Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            # Index bereinigen für Chart (nur Monat_Jahr behalten)
            agg = agg.reset_index().set_index('Monat_Jahr').sort_values('sort_key')
            chart_data = agg[['SOLL', 'IST']] if 'SOLL' in agg and 'IST' in agg else agg
            
        elif view_mode == "Quartalsweise":
            agg = df.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0)
            chart_data = agg
        else:
            agg = df.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            chart_data = agg

        # Chart
        st.bar_chart(chart_data)
        
        st.subheader("Ausgaben nach Kategorie")
        # Nur IST Werte betrachten für Ausgabenverteilung
        df_ist = df[df['type'] == 'IST']
        if not df_ist.empty:
            cat_agg = df_ist.groupby('category')['amount'].sum().sort_values(ascending=False)
            st.bar_chart(cat_agg)
        else:
            st.info("Keine Ausgabendaten vorhanden.")

    # --- TAB 3: Vergleichsrechner ---
    with tab3:
        st.subheader("📊 Periodenvergleich")
        st.write("Vergleiche zwei Zeiträume, um zu sehen, wo sich deine Ausgaben (IST) verändert haben.")
        
        # Wir brauchen zwei Filter: Basiszeitraum und Vergleichszeitraum
        # Wir nutzen die oben erstellten Helper Columns
        all_periods = []
        # Kombinierte Liste aus Monaten, Quartalen und Jahren erstellen
        all_periods += [f"Monat: {x}" for x in df['Monat_Jahr'].unique()]
        all_periods += [f"Quartal: {x}" for x in df['Quartal'].unique()]
        all_periods += [f"Jahr: {x}" for x in df['Jahr'].unique()]
        
        col_v1, col_v2 = st.columns(2)
        
        with col_v1:
            p1_sel = st.selectbox("Zeitraum A (Basis)", all_periods, index=0 if len(all_periods) > 0 else None)
        with col_v2:
            # Versuche den zweiten Eintrag als Default zu nehmen (Vormonat)
            def_idx = 1 if len(all_periods) > 1 else 0
            p2_sel = st.selectbox("Zeitraum B (Vergleich)", all_periods, index=def_idx)

        if p1_sel and p2_sel:
            # Helper Funktion zum Filtern
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
            
            # Wir schauen uns nur die IST-Ausgaben an (oder willst du auch Budgets vergleichen? Meist ist IST interessanter)
            # Hier: Fokus auf IST
            def get_cat_sums(dframe):
                return dframe[dframe['type'] == 'IST'].groupby('category')['amount'].sum()

            sum_a = get_cat_sums(df_a)
            sum_b = get_cat_sums(df_b)
            
            # Zusammenführen
            comp_df = pd.DataFrame({'Basis (€)': sum_a, 'Vergleich (€)': sum_b}).fillna(0)
            
            # Berechnung der Differenz
            # Differenz: Wenn Basis (dieser Monat) höher ist als Vergleich (letzter Monat), hast du MEHR ausgegeben (+).
            comp_df['Differenz (€)'] = comp_df['Basis (€)'] - comp_df['Vergleich (€)']
            
            # Prozentuale Abweichung (Vorsicht bei Div durch 0)
            def calc_pct(row):
                if row['Vergleich (€)'] == 0:
                    return 100.0 if row['Basis (€)'] > 0 else 0.0
                return (row['Differenz (€)'] / row['Vergleich (€)']) * 100
                
            comp_df['Veränderung %'] = comp_df.apply(calc_pct, axis=1)
            
            # Gesamtzeile
            total_row = pd.DataFrame({
                'Basis (€)': [comp_df['Basis (€)'].sum()],
                'Vergleich (€)': [comp_df['Vergleich (€)'].sum()],
                'Differenz (€)': [comp_df['Basis (€)'].sum() - comp_df['Vergleich (€)'].sum()]
            }, index=['GESAMT'])
            total_row['Veränderung %'] = total_row.apply(calc_pct, axis=1)
            
            # Zusammenfügen: Gesamtzeile oben oder unten? Unten ist klassisch.
            comp_df = pd.concat([comp_df, total_row])

            # Anzeigen
            st.write(f"Vergleich: **{p1_sel}** vs. **{p2_sel}**")
            
            # Styling
            def style_negative_red_positive_green(val):
                """
                Bei Ausgaben: 
                Positiv (+) bedeutet MEHR ausgegeben -> Schlecht (Rot)
                Negativ (-) bedeutet WENIGER ausgegeben -> Gut (Grün)
                """
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
            
            st.caption("Legende: Grüne Zahlen bedeuten, du hast im Basis-Zeitraum WENIGER ausgegeben als im Vergleichszeitraum (Geld gespart). Rote Zahlen bedeuten höhere Ausgaben.")
