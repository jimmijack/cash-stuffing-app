import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date
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
    "Sonstiges", "Fixkosten", "Kleidung", "Geschenke"
]

def format_euro(val):
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY
        )
    ''')
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
        success = False
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
            df['Monat_Num'] = df['date'].dt.month
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

# --- SIDEBAR ---
st.sidebar.header("Neuer Eintrag")
current_categories = get_categories()

with st.sidebar.form("entry_form", clear_on_submit=True):
    date_input = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
    type_input = st.selectbox("Typ", ["SOLL (Budget)", "IST (Ausgabe)"])
    if not current_categories:
        st.warning("Keine Kategorien vorhanden.")
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
with st.sidebar.expander("⚙️ Kategorien verwalten"):
    new_cat_name = st.text_input("Name hinzufügen", key="new_cat_input")
    if st.button("Hinzufügen"):
        if new_cat_name:
            if add_category_to_db(new_cat_name):
                st.rerun()
    
    st.markdown("---")
    del_cat_name = st.selectbox("Löschen", current_categories, key="del_cat_select") if current_categories else None
    if st.button("Löschen"):
        if del_cat_name:
            delete_category_from_db(del_cat_name)
            st.rerun()

# --- HAUPTBEREICH ---
df = load_data()

if df.empty:
    st.info("Bitte erstelle erste Einträge in der Sidebar.")
else:
    tab1, tab2, tab3, tab4 = st.tabs(["📅 Monatsübersicht", "📈 Jahres-Vergleich (Chart)", "📊 Trends", "⚖️ Perioden-Vergleich"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        # Sort key generieren
        df['sort_key'] = df['date'].dt.year * 100 + df['date'].dt.month
        month_options = df[['Monat_Jahr', 'sort_key']].drop_duplicates().sort_values('sort_key', ascending=False)
        
        if not month_options.empty:
            selected_month_str = st.selectbox("Monat auswählen", month_options['Monat_Jahr'].unique())
            df_month = df[df['Monat_Jahr'] == selected_month_str].copy()
            
            pivot = df_month.groupby(['category', 'type'])['amount'].sum().unstack(fill_value=0)
            if 'SOLL' not in pivot.columns: pivot['SOLL'] = 0.0
            if 'IST' not in pivot.columns: pivot['IST'] = 0.0
            
            pivot['Verfügbar'] = pivot['SOLL'] - pivot['IST']
            pivot['Genutzt %'] = (pivot['IST'] / pivot['SOLL'] * 100).fillna(0)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Gesamt Budget", format_euro(pivot['SOLL'].sum()))
            col2.metric("Gesamt Ausgaben", format_euro(pivot['IST'].sum()))
            col3.metric("Restbetrag", format_euro(pivot['SOLL'].sum() - pivot['IST'].sum()))
            
            st.dataframe(pivot.style.format("{:.2f} €", subset=['SOLL', 'IST', 'Verfügbar']).format("{:.1f} %", subset=['Genutzt %']).background_gradient(cmap="RdYlGn_r", subset=['Genutzt %'], vmin=0, vmax=120), use_container_width=True)
            
            with st.expander("Einzelbuchungen"):
                st.dataframe(df_month[['date', 'category', 'description', 'amount', 'type']].sort_values(by='date', ascending=False).style.format({"date": lambda t: t.strftime("%d.%m.%Y"), "amount": "{:.2f} €"}), hide_index=True, use_container_width=True)

    # --- TAB 2: TR STYLE JAHRESVERGLEICH ---
    with tab2:
        st.subheader("📈 Ausgaben-Verlauf im Vergleich")
        
        cat_options = ["Alle"] + sorted(current_categories)
        selected_cat_chart = st.selectbox("Kategorie filtern", cat_options, index=0)
        
        available_years = sorted(df['Jahr'].unique())
        if not available_years:
            st.write("Keine Daten.")
        else:
            col_y1, col_y2 = st.columns(2)
            current_year = date.today().year
            idx_current = available_years.index(current_year) if current_year in available_years else len(available_years)-1
            idx_last = idx_current - 1 if idx_current > 0 else idx_current
            
            with col_y1: year_a = st.selectbox("Jahr A (Hauptlinie)", available_years, index=idx_current)
            with col_y2: year_b = st.selectbox("Jahr B (Vergleich)", available_years, index=idx_last)
                
            df_chart = df[df['type'] == 'IST'].copy()
            if selected_cat_chart != "Alle":
                df_chart = df_chart[df_chart['category'] == selected_cat_chart]
                
            def get_monthly_sums(dframe, y):
                d_y = dframe[dframe['Jahr'] == y]
                sums = d_y.groupby('Monat_Num')['amount'].sum()
                sums = sums.reindex(range(1, 13), fill_value=0)
                return sums

            data_a = get_monthly_sums(df_chart, year_a)
            data_b = get_monthly_sums(df_chart, year_b)
            
            month_labels = [DE_MONTHS[i] for i in range(1, 13)]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=month_labels, y=data_a.values, mode='lines+markers', name=str(year_a),
                line=dict(color='#0055ff', width=4), fill='tozeroy', fillcolor='rgba(0, 85, 255, 0.1)'))
            fig.add_trace(go.Scatter(x=month_labels, y=data_b.values, mode='lines+markers', name=str(year_b),
                line=dict(color='gray', width=2, dash='dot')))

            fig.update_layout(title=f"Ausgaben: {selected_cat_chart}", xaxis_title="", yaxis_title="Betrag in €",
                template="plotly_white", hovermode="x unified", legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                margin=dict(l=20, r=20, t=40, b=20))
            fig.update_yaxes(tickprefix="", ticksuffix=" €")
            st.plotly_chart(fig, use_container_width=True)

    # --- TAB 3: Trends (FIXED) ---
    with tab3:
        st.subheader("Balken-Übersicht")
        view_mode = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True, key="trend_radio")
        
        # Sicherstellen, dass Daten da sind
        if view_mode == "Monatlich":
            # 1. Gruppieren
            agg = df.groupby(['sort_key', 'Monat_Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            
            # 2. Reset Index um sauber sortieren zu können
            agg = agg.reset_index()
            
            # 3. Sortieren
            agg = agg.sort_values('sort_key')
            
            # 4. Sauberes DataFrame für Streamlit: Index = String (Name), Columns = Values
            # Wir setzen Monat_Jahr als Index und nehmen nur die Spalten, die wir brauchen
            agg = agg.set_index('Monat_Jahr')
            
            # Prüfen welche Spalten existieren (falls noch kein IST oder SOLL da ist)
            cols_to_plot = []
            if 'SOLL' in agg.columns: cols_to_plot.append('SOLL')
            if 'IST' in agg.columns: cols_to_plot.append('IST')
            
            st.bar_chart(agg[cols_to_plot])
            
        elif view_mode == "Quartalsweise":
            chart_data = df.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0)
            st.bar_chart(chart_data)
        else:
            chart_data = df.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            st.bar_chart(chart_data)

    # --- TAB 4: Vergleich ---
    with tab4:
        st.subheader("📊 Detaillierter Vergleich")
        all_periods = [f"Monat: {x}" for x in df['Monat_Jahr'].unique()] + [f"Quartal: {x}" for x in df['Quartal'].unique()] + [f"Jahr: {x}" for x in df['Jahr'].unique()]
        
        if not all_periods:
            st.write("Nicht genug Daten.")
        else:
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Basis", all_periods, key="p1")
            p2 = c2.selectbox("Vergleich", all_periods, key="p2", index=1 if len(all_periods)>1 else 0)
            
            if p1 and p2:
                def filter_p(sel):
                    t, v = sel.split(": ")
                    if t=="Monat": return df[df['Monat_Jahr']==v]
                    if t=="Quartal": return df[df['Quartal']==v]
                    if t=="Jahr": return df[df['Jahr'].astype(str)==v]
                    return pd.DataFrame()
                
                df_a, df_b = filter_p(p1), filter_p(p2)
                
                # Check ob DataFrames leer sind
                if df_a.empty or df_b.empty:
                    st.warning("Einer der gewählten Zeiträume hat keine Daten.")
                else:
                    sum_a = df_a[df_a['type']=='IST'].groupby('category')['amount'].sum()
                    sum_b = df_b[df_b['type']=='IST'].groupby('category')['amount'].sum()
                    
                    comp = pd.DataFrame({'Basis': sum_a, 'Vgl': sum_b}).fillna(0)
                    comp['Diff'] = comp['Basis'] - comp['Vgl']
                    comp['%'] = comp.apply(lambda r: (r['Diff']/r['Vgl']*100) if r['Vgl']!=0 else (100 if r['Basis']>0 else 0), axis=1)
                    
                    st.dataframe(comp.style.format("{:.2f} €", subset=['Basis','Vgl','Diff']).format("{:+.1f} %", subset=['%']).applymap(lambda v: f'color: {"red" if v>0 else "green"}; font-weight: bold' if v!=0 else 'color:black', subset=['Diff', '%']), use_container_width=True)
