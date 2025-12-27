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
            # Sortierschlüssel für Dropdowns
            df['sort_key_month'] = df['Jahr'] * 100 + df['Monat_Num']
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
    tab1, tab2, tab3, tab4 = st.tabs(["📅 Monatsübersicht", "📈 Verlauf (Chart)", "📊 Trends (Balken)", "⚖️ Perioden-Vergleich"])

    # --- TAB 1: Monatsübersicht ---
    with tab1:
        st.subheader("Details pro Monat")
        month_options = df[['Monat_Jahr', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
        
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

    # --- TAB 2: VERLAUF CHART (NEU: MONATE, QUARTALE, JAHRE) ---
    with tab2:
        st.subheader("📈 Ausgaben-Verlauf im Vergleich")
        
        # 1. Modus Auswahl
        mode = st.radio("Vergleichs-Modus", ["Monate (Tag 1-31)", "Jahre (Jan-Dez)", "Quartale (Monat 1-3)"], horizontal=True)
        
        # Kategorie Filter
        cat_options = ["Alle"] + sorted(current_categories)
        selected_cat_chart = st.selectbox("Kategorie filtern", cat_options, index=0)
        
        # Basis DataFrame filtern (Nur IST Ausgaben)
        df_chart = df[df['type'] == 'IST'].copy()
        if selected_cat_chart != "Alle":
            df_chart = df_chart[df_chart['category'] == selected_cat_chart]

        # Initialisierung der Plot-Variablen
        x_labels = []
        data_a = []
        data_b = []
        name_a = ""
        name_b = ""
        
        # --- LOGIK: MONATS-VERGLEICH ---
        if "Monate" in mode:
            # Optionen laden (sortiert)
            m_opts = df[['Monat_Jahr', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            all_months = m_opts['Monat_Jahr'].unique()
            
            if len(all_months) < 1:
                st.write("Nicht genügend Daten für Monatsvergleich.")
            else:
                col_m1, col_m2 = st.columns(2)
                with col_m1: name_a = st.selectbox("Monat A (Blau)", all_months, index=0)
                with col_m2: name_b = st.selectbox("Monat B (Grau)", all_months, index=1 if len(all_months)>1 else 0)
                
                # Funktion: Gruppieren nach Tag (1-31)
                def get_daily_sums(dframe, m_str):
                    d_m = dframe[dframe['Monat_Jahr'] == m_str]
                    sums = d_m.groupby(d_m['date'].dt.day)['amount'].sum()
                    sums = sums.reindex(range(1, 32), fill_value=0) # Alle Tage 1-31 auffüllen
                    return sums

                data_a = get_daily_sums(df_chart, name_a)
                data_b = get_daily_sums(df_chart, name_b)
                x_labels = list(range(1, 32))

        # --- LOGIK: JAHRES-VERGLEICH ---
        elif "Jahre" in mode:
            years = sorted(df['Jahr'].unique())
            if not years:
                st.write("Keine Jahresdaten.")
            else:
                col_y1, col_y2 = st.columns(2)
                curr_y = date.today().year
                idx_curr = years.index(curr_y) if curr_y in years else len(years)-1
                idx_last = idx_curr - 1 if idx_curr > 0 else idx_curr
                
                with col_y1: name_a = st.selectbox("Jahr A (Blau)", years, index=idx_curr)
                with col_y2: name_b = st.selectbox("Jahr B (Grau)", years, index=idx_last)
                
                def get_monthly_sums(dframe, y):
                    d_y = dframe[dframe['Jahr'] == y]
                    sums = d_y.groupby('Monat_Num')['amount'].sum()
                    sums = sums.reindex(range(1, 13), fill_value=0)
                    return sums

                data_a = get_monthly_sums(df_chart, name_a)
                data_b = get_monthly_sums(df_chart, name_b)
                x_labels = [DE_MONTHS[i] for i in range(1, 13)]
                name_a, name_b = str(name_a), str(name_b)

        # --- LOGIK: QUARTALS-VERGLEICH ---
        else:
            qs = sorted(df['Quartal'].unique(), reverse=True)
            if not qs:
                st.write("Keine Quartalsdaten.")
            else:
                col_q1, col_q2 = st.columns(2)
                with col_q1: name_a = st.selectbox("Quartal A (Blau)", qs, index=0)
                with col_q2: name_b = st.selectbox("Quartal B (Grau)", qs, index=1 if len(qs)>1 else 0)
                
                # Helper: Relativer Monat im Quartal (1, 2, 3)
                # Modulo Arithmetik: (Month - 1) % 3 + 1 -> Gibt 1, 2 oder 3 zurück
                def get_q_month_sums(dframe, q_str):
                    d_q = dframe[dframe['Quartal'] == q_str].copy()
                    if d_q.empty: return pd.Series([0,0,0], index=[1,2,3])
                    d_q['rel_month'] = (d_q['date'].dt.month - 1) % 3 + 1
                    sums = d_q.groupby('rel_month')['amount'].sum()
                    sums = sums.reindex(range(1, 4), fill_value=0)
                    return sums

                data_a = get_q_month_sums(df_chart, name_a)
                data_b = get_q_month_sums(df_chart, name_b)
                x_labels = ["1. Monat", "2. Monat", "3. Monat"]

        # --- PLOTLY CHART ERSTELLEN ---
        if len(data_a) > 0:
            fig = go.Figure()

            # Linie A (Blau, gefüllt)
            fig.add_trace(go.Scatter(
                x=x_labels, y=data_a.values,
                mode='lines+markers', name=name_a,
                line=dict(color='#0055ff', width=3),
                fill='tozeroy', fillcolor='rgba(0, 85, 255, 0.1)'
            ))

            # Linie B (Grau, gestrichelt)
            fig.add_trace(go.Scatter(
                x=x_labels, y=data_b.values,
                mode='lines+markers', name=name_b,
                line=dict(color='gray', width=2, dash='dot')
            ))

            fig.update_layout(
                title=f"{selected_cat_chart}: {name_a} vs. {name_b}",
                yaxis_title="Ausgaben in €",
                template="plotly_white",
                hovermode="x unified",
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                margin=dict(l=20, r=20, t=40, b=20)
            )
            fig.update_yaxes(tickprefix="", ticksuffix=" €")
            
            # X-Achsen Label anpassen je nach Modus
            if "Monate" in mode:
                fig.update_xaxes(title="Tag des Monats", tickmode='linear', tick0=1, dtick=1)
            elif "Jahre" in mode:
                fig.update_xaxes(title="Monat")
            else:
                fig.update_xaxes(title="Monat im Quartal")

            st.plotly_chart(fig, use_container_width=True)
            
            # Summen Vergleich
            sum_a = data_a.sum()
            sum_b = data_b.sum()
            diff = sum_a - sum_b
            
            c_res1, c_res2, c_res3 = st.columns(3)
            c_res1.metric(f"Summe {name_a}", format_euro(sum_a))
            c_res2.metric(f"Summe {name_b}", format_euro(sum_b))
            c_res3.metric("Differenz", format_euro(diff), delta=format_euro(diff), delta_color="inverse") # inverse: Rot wenn A > B (mehr Ausgaben)

    # --- TAB 3: Trends (Balken) ---
    with tab3:
        st.subheader("Balken-Übersicht")
        view_mode = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True, key="trend_radio")
        
        if view_mode == "Monatlich":
            agg = df.groupby(['sort_key_month', 'Monat_Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            agg = agg.reset_index().sort_values('sort_key_month').set_index('Monat_Jahr')
            cols_to_plot = [c for c in ['SOLL', 'IST'] if c in agg.columns]
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
                
                if df_a.empty or df_b.empty:
                    st.warning("Keine Daten für Auswahl.")
                else:
                    sum_a = df_a[df_a['type']=='IST'].groupby('category')['amount'].sum()
                    sum_b = df_b[df_b['type']=='IST'].groupby('category')['amount'].sum()
                    
                    comp = pd.DataFrame({'Basis': sum_a, 'Vgl': sum_b}).fillna(0)
                    comp['Diff'] = comp['Basis'] - comp['Vgl']
                    comp['%'] = comp.apply(lambda r: (r['Diff']/r['Vgl']*100) if r['Vgl']!=0 else (100 if r['Basis']>0 else 0), axis=1)
                    
                    st.dataframe(comp.style.format("{:.2f} €", subset=['Basis','Vgl','Diff']).format("{:+.1f} %", subset=['%']).applymap(lambda v: f'color: {"red" if v>0 else "green"}; font-weight: bold' if v!=0 else 'color:black', subset=['Diff', '%']), use_container_width=True)
