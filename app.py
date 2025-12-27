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

def update_db_from_changes(changes):
    """Verarbeitet Änderungen aus dem DataEditor"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Gelöschte Zeilen
    for index in changes["deleted_rows"]:
        # Wir brauchen die ID der gelöschten Zeile. 
        # Da wir im Editor den originalen DataFrame index nutzen, müssen wir aufpassen.
        # Der Editor gibt uns den Index im DataFrame.
        # Wir holen die ID im Hauptteil des Codes, hier führen wir nur SQL aus.
        pass # Logik wird direkt im UI Teil gemacht, da wir Zugriff auf DF brauchen
        
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
    # REITER DEFINITION
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📅 Monatsübersicht", "📈 Verlauf (Chart)", "📊 Trends (Balken)", "⚖️ Vergleich", "📝 Buchungen korrigieren"])

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

    # --- TAB 2: VERLAUF CHART ---
    with tab2:
        st.subheader("📈 Ausgaben-Verlauf")
        mode = st.radio("Vergleichs-Modus", ["Monate (Tag 1-31)", "Jahre (Jan-Dez)", "Quartale (Monat 1-3)"], horizontal=True)
        cat_options = ["Alle"] + sorted(current_categories)
        selected_cat_chart = st.selectbox("Kategorie filtern", cat_options, index=0)
        
        df_chart = df[df['type'] == 'IST'].copy()
        if selected_cat_chart != "Alle":
            df_chart = df_chart[df_chart['category'] == selected_cat_chart]

        x_labels, data_a, data_b, name_a, name_b = [], [], [], "", ""
        
        if "Monate" in mode:
            m_opts = df[['Monat_Jahr', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            all_months = m_opts['Monat_Jahr'].unique()
            if len(all_months) >= 1:
                c1, c2 = st.columns(2)
                with c1: name_a = st.selectbox("A (Blau)", all_months, index=0)
                with c2: name_b = st.selectbox("B (Grau)", all_months, index=1 if len(all_months)>1 else 0)
                
                def get_d(dframe, m):
                    d = dframe[dframe['Monat_Jahr'] == m]
                    return d.groupby(d['date'].dt.day)['amount'].sum().reindex(range(1, 32), fill_value=0)
                
                data_a, data_b = get_d(df_chart, name_a), get_d(df_chart, name_b)
                x_labels = list(range(1, 32))
        
        elif "Jahre" in mode:
            years = sorted(df['Jahr'].unique())
            if years:
                curr_y = date.today().year
                idx = years.index(curr_y) if curr_y in years else len(years)-1
                c1, c2 = st.columns(2)
                with c1: name_a = st.selectbox("A", years, index=idx)
                with c2: name_b = st.selectbox("B", years, index=idx-1 if idx>0 else idx)
                
                def get_y(dframe, y):
                    return dframe[dframe['Jahr']==y].groupby('Monat_Num')['amount'].sum().reindex(range(1,13), fill_value=0)
                data_a, data_b = get_y(df_chart, name_a), get_y(df_chart, name_b)
                x_labels = [DE_MONTHS[i] for i in range(1,13)]
                name_a, name_b = str(name_a), str(name_b)
        else:
            qs = sorted(df['Quartal'].unique(), reverse=True)
            if qs:
                c1, c2 = st.columns(2)
                with c1: name_a = st.selectbox("A", qs, index=0)
                with c2: name_b = st.selectbox("B", qs, index=1 if len(qs)>1 else 0)
                def get_q(dframe, q):
                    d = dframe[dframe['Quartal']==q].copy()
                    if d.empty: return pd.Series([0,0,0], index=[1,2,3])
                    d['rm'] = (d['date'].dt.month-1)%3+1
                    return d.groupby('rm')['amount'].sum().reindex(range(1,4), fill_value=0)
                data_a, data_b = get_q(df_chart, name_a), get_q(df_chart, name_b)
                x_labels = ["1. Monat", "2. Monat", "3. Monat"]

        if len(data_a) > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x_labels, y=data_a.values, mode='lines+markers', name=name_a, line=dict(color='#0055ff', width=3), fill='tozeroy', fillcolor='rgba(0, 85, 255, 0.1)'))
            fig.add_trace(go.Scatter(x=x_labels, y=data_b.values, mode='lines+markers', name=name_b, line=dict(color='gray', width=2, dash='dot')))
            fig.update_layout(title=f"{selected_cat_chart}: {name_a} vs {name_b}", yaxis_title="€", template="plotly_white", hovermode="x unified", legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01), margin=dict(l=20, r=20, t=40, b=20))
            if "Monate" in mode: fig.update_xaxes(title="Tag", tickmode='linear', tick0=1, dtick=1)
            st.plotly_chart(fig, use_container_width=True)

    # --- TAB 3: Trends ---
    with tab3:
        st.subheader("Balken-Übersicht")
        view_mode = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True, key="trend_radio")
        if view_mode == "Monatlich":
            agg = df.groupby(['sort_key_month', 'Monat_Jahr', 'type'])['amount'].sum().unstack(fill_value=0)
            agg = agg.reset_index().sort_values('sort_key_month').set_index('Monat_Jahr')
            cols = [c for c in ['SOLL', 'IST'] if c in agg.columns]
            st.bar_chart(agg[cols])
        elif view_mode == "Quartalsweise":
            st.bar_chart(df.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0))
        else:
            st.bar_chart(df.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0))

    # --- TAB 4: Vergleich ---
    with tab4:
        st.subheader("📊 Detaillierter Vergleich")
        all_p = [f"Monat: {x}" for x in df['Monat_Jahr'].unique()] + [f"Quartal: {x}" for x in df['Quartal'].unique()] + [f"Jahr: {x}" for x in df['Jahr'].unique()]
        if all_p:
            c1, c2 = st.columns(2)
            p1 = c1.selectbox("Basis", all_p, key="p1")
            p2 = c2.selectbox("Vgl", all_p, key="p2", index=1 if len(all_p)>1 else 0)
            if p1 and p2:
                def f_p(sel):
                    t, v = sel.split(": ")
                    if t=="Monat": return df[df['Monat_Jahr']==v]
                    if t=="Quartal": return df[df['Quartal']==v]
                    if t=="Jahr": return df[df['Jahr'].astype(str)==v]
                    return pd.DataFrame()
                df_a, df_b = f_p(p1), f_p(p2)
                if not df_a.empty and not df_b.empty:
                    s_a, s_b = df_a[df_a['type']=='IST'].groupby('category')['amount'].sum(), df_b[df_b['type']=='IST'].groupby('category')['amount'].sum()
                    comp = pd.DataFrame({'Basis': s_a, 'Vgl': s_b}).fillna(0)
                    comp['Diff'], comp['%'] = comp['Basis']-comp['Vgl'], comp.apply(lambda r: (r['Basis']-r['Vgl'])/r['Vgl']*100 if r['Vgl']!=0 else (100 if r['Basis']>0 else 0), axis=1)
                    st.dataframe(comp.style.format("{:.2f} €", subset=['Basis','Vgl','Diff']).format("{:+.1f} %", subset=['%']).applymap(lambda v: f'color: {"red" if v>0 else "green"}; font-weight: bold' if v!=0 else 'color:black', subset=['Diff', '%']), use_container_width=True)

    # --- TAB 5: KORREKTUREN (EDITOR) ---
    with tab5:
        st.subheader("📝 Buchungen bearbeiten")
        st.write("Hier kannst du Tippfehler korrigieren oder falsche Buchungen löschen. Änderungen werden sofort gespeichert.")
        
        # 1. Daten laden für den Editor (Wir brauchen die 'id' Spalte, verstecken sie aber optisch nicht zwingend, oder machen sie disabled)
        # Sortieren nach Datum neu -> alt
        df_edit = df.sort_values(by=['date', 'id'], ascending=[False, False]).copy()
        
        # Wir formatieren das Datum für den Editor passend
        # Streamlit DataEditor kommt gut mit datetime objekten klar
        
        # Spaltenkonfiguration
        column_config = {
            "id": st.column_config.NumberColumn("ID", disabled=True), # ID darf nicht geändert werden
            "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
            "category": st.column_config.SelectboxColumn("Kategorie", options=current_categories, required=True),
            "type": st.column_config.SelectboxColumn("Typ", options=["SOLL", "IST"], required=True),
            "amount": st.column_config.NumberColumn("Betrag (€)", format="%.2f €", min_value=0),
            "description": st.column_config.TextColumn("Beschreibung"),
            # Wir verstecken die Hilfsspalten
            "Monat_Name": None, "Monat_Num": None, "Jahr": None, "Monat_Jahr": None, "Quartal": None, "sort_key_month": None, "sort_key": None
        }
        
        # Der Editor
        edited_df = st.data_editor(
            df_edit,
            key="transaction_editor",
            column_config=column_config,
            num_rows="dynamic", # Erlaubt Löschen und Hinzufügen (wobei Hinzufügen wir hier eher ignorieren, sidebar ist besser)
            use_container_width=True,
            hide_index=True
        )
        
        # Logik zum Speichern der Änderungen
        # Streamlit session_state trackt Änderungen
        if st.session_state["transaction_editor"]:
            changes = st.session_state["transaction_editor"]
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            has_changes = False
            
            # 1. GELÖSCHTE ZEILEN (deleted_rows gibt Indices im angezeigten DF zurück)
            if changes["deleted_rows"]:
                # Liste der gelöschten Indizes (Positionen im df_edit)
                deleted_indices = changes["deleted_rows"]
                # Wir müssen die IDs der gelöschten Zeilen aus dem originalen df_edit holen
                ids_to_delete = [df_edit.iloc[i]['id'] for i in deleted_indices]
                
                for del_id in ids_to_delete:
                    c.execute("DELETE FROM transactions WHERE id = ?", (int(del_id),))
                has_changes = True

            # 2. BEARBEITETE ZEILEN (edited_rows ist ein Dict {index: {col: new_val}})
            if changes["edited_rows"]:
                for idx, col_changes in changes["edited_rows"].items():
                    # ID der betroffenen Zeile
                    row_id = df_edit.iloc[idx]['id']
                    
                    for col_name, new_value in col_changes.items():
                        # Datum muss evtl konvertiert werden
                        if col_name == "date":
                            # new_value ist hier oft ein String im ISO format (YYYY-MM-DD)
                            pass 
                        
                        query = f"UPDATE transactions SET {col_name} = ? WHERE id = ?"
                        c.execute(query, (new_value, int(row_id)))
                has_changes = True
            
            # 3. NEUE ZEILEN (added_rows) - Optional, falls jemand unten auf "+" klickt
            if changes["added_rows"]:
                for row in changes["added_rows"]:
                    # Default Werte abfangen, falls user nicht alles ausfüllt
                    dt = row.get("date", date.today())
                    cat = row.get("category", current_categories[0] if current_categories else "Sonstiges")
                    desc = row.get("description", "")
                    amt = row.get("amount", 0.0)
                    typ = row.get("type", "IST")
                    
                    c.execute("INSERT INTO transactions (date, category, description, amount, type) VALUES (?, ?, ?, ?, ?)",
                              (dt, cat, desc, amt, typ))
                has_changes = True

            if has_changes:
                conn.commit()
                conn.close()
                st.success("Änderungen gespeichert!")
                st.rerun() # Seite neu laden, um DB Update anzuzeigen
            else:
                conn.close()
