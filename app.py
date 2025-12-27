import streamlit as st
import pandas as pd
import sqlite3
import datetime
from datetime import date, timedelta
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

def format_euro(val):
    return "{:,.2f} €".format(val).replace(",", "X").replace(".", ",").replace("X", ".")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Transaktionen Tabelle
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
    
    # 2. Migration: Neue Spalte 'budget_month' hinzufügen, falls sie fehlt
    # Das löst dein Problem mit dem 29.10. -> November
    try:
        c.execute("SELECT budget_month FROM transactions LIMIT 1")
    except sqlite3.OperationalError:
        # Spalte existiert nicht, wir fügen sie hinzu
        c.execute("ALTER TABLE transactions ADD COLUMN budget_month TEXT")
        # Bestehende Daten patchen: Budget-Monat = Monat des Datums
        c.execute("UPDATE transactions SET budget_month = strftime('%Y-%m', date) WHERE budget_month IS NULL")
        conn.commit()

    # 3. Kategorien Tabelle
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
            # Hilfsspalten
            df['Monat_Name'] = df['date'].dt.month.map(DE_MONTHS)
            df['Monat_Num'] = df['date'].dt.month
            df['Jahr'] = df['date'].dt.year
            df['Quartal'] = "Q" + df['date'].dt.quarter.astype(str) + " " + df['Jahr'].astype(str)
            
            # WICHTIG: Zuordnung für die Statistik
            # IST (Ausgaben) zählen immer zum Datum, an dem sie passiert sind
            # SOLL (Budget) zählt zu dem Monat, für den es gedacht ist ('budget_month')
            
            # Wir bauen eine einheitliche 'Analysis_Month' Spalte
            # Wenn budget_month leer ist (Legacy Data), nimm das Datum
            df['budget_month'] = df['budget_month'].fillna(df['date'].dt.strftime('%Y-%m'))
            
            def get_analysis_month(row):
                if row['type'] == 'SOLL':
                    # Beim Budget zählt der Zielmonat (z.B. "2025-11")
                    y, m = map(int, row['budget_month'].split('-'))
                    return f"{DE_MONTHS[m]} {y}"
                else:
                    # Bei Ausgaben zählt das Datum
                    return f"{DE_MONTHS[row['date'].month]} {row['date'].year}"

            df['Analyse_Monat'] = df.apply(get_analysis_month, axis=1)
            
            # Sortierschlüssel (YYYYMM) für den Analyse Monat berechnen
            def get_sort_key(row):
                if row['type'] == 'SOLL':
                     parts = row['budget_month'].split('-')
                     return int(parts[0]) * 100 + int(parts[1])
                else:
                    return row['date'].year * 100 + row['date'].month
            
            df['sort_key_month'] = df.apply(get_sort_key, axis=1)

        return df
    except Exception as e:
        st.error(f"Ladefehler: {e}")
        return pd.DataFrame()

def save_transaction(dt, cat, desc, amt, typ, budget_mon=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Wenn kein expliziter Budget-Monat, nimm den vom Datum
    if not budget_mon:
        budget_mon = dt.strftime("%Y-%m")
        
    c.execute("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?, ?, ?, ?, ?, ?)",
              (dt, cat, desc, amt, typ, budget_mon))
    conn.commit()
    conn.close()

def perform_transfer(date_val, cat_from, cat_to, amount):
    """Führt eine Umbuchung durch: Minus im Budget A, Plus im Budget B"""
    # 1. Abgang beim Sender (Wir reduzieren sein Budget)
    # Wir buchen das als negatives SOLL. Warum? Weil eine Umbuchung keine Ausgabe (IST) ist,
    # sondern eine Budget-Korrektur. 
    # Wenn wir IST nehmen würden, würde es so aussehen, als hätten wir Geld ausgegeben.
    save_transaction(date_val, cat_from, f"Umbuchung zu {cat_to}", -amount, "SOLL", date_val.strftime("%Y-%m"))
    
    # 2. Zugang beim Empfänger
    save_transaction(date_val, cat_to, f"Umbuchung von {cat_from}", amount, "SOLL", date_val.strftime("%Y-%m"))

# Initialisierung
try:
    init_db()
except Exception as e:
    st.error(f"Datenbankfehler: {e}")

# --- UI START ---
st.title("💶 Mein Cash Stuffing Planer")

# --- SIDEBAR ---
sb_tab1, sb_tab2 = st.sidebar.tabs(["📝 Neuer Eintrag", "💸 Umbuchung"])
current_categories = get_categories()

# TAB 1: EINTARG
with sb_tab1:
    with st.form("entry_form", clear_on_submit=True):
        date_input = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        type_input = st.selectbox("Typ", ["SOLL (Budget einzahlen)", "IST (Ausgabe)"])
        
        # LOGIK: BUDGET MONAT WÄHLEN
        # Wenn SOLL gewählt ist, zeige Auswahl für Zielmonat
        budget_target = None
        if "SOLL" in type_input:
            st.caption("Für welchen Monat ist dieses Budget?")
            today = date.today()
            # Optionen: Dieser Monat, Nächster Monat
            this_month_str = today.strftime("%Y-%m")
            next_month_date = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            next_month_str = next_month_date.strftime("%Y-%m")
            
            # Formatieren für Anzeige
            this_lbl = f"{DE_MONTHS[today.month]} {today.year}"
            next_lbl = f"{DE_MONTHS[next_month_date.month]} {next_month_date.year}"
            
            choice = st.radio("Zuweisung", [this_lbl, next_lbl], horizontal=True)
            budget_target = this_month_str if choice == this_lbl else next_month_str
        
        if not current_categories:
            st.warning("Keine Kategorien vorhanden.")
            category_input = st.text_input("Kategorie")
        else:
            category_input = st.selectbox("Kategorie", current_categories)
            
        desc_input = st.text_input("Beschreibung (Optional)")
        amount_input = st.number_input("Betrag (€)", min_value=0.0, format="%.2f")
        
        submitted = st.form_submit_button("Speichern")
        if submitted:
            db_type = "SOLL" if "SOLL" in type_input else "IST"
            save_transaction(date_input, category_input, desc_input, amount_input, db_type, budget_target)
            st.success("Gespeichert!")
            st.rerun()

# TAB 2: UMBUCHUNG
with sb_tab2:
    st.write("Verschiebe Geld von einem Umschlag in einen anderen (z.B. Restbetrag in Spar-Topf).")
    with st.form("transfer_form", clear_on_submit=True):
        t_date = st.date_input("Datum", date.today(), format="DD.MM.YYYY")
        if len(current_categories) >= 2:
            c1, c2 = st.columns(2)
            cat_from = c1.selectbox("Von (Quelle)", current_categories, index=0)
            # Versuche intelligenten Default für Ziel (z.B. Sparen oder Notgroschen)
            def_idx = 1
            for i, c in enumerate(current_categories):
                if "Spar" in c or "Notgroschen" in c:
                    if c != cat_from:
                        def_idx = i
                        break
            cat_to = c2.selectbox("Nach (Ziel)", current_categories, index=def_idx)
            
            t_amt = st.number_input("Betrag (€)", min_value=0.0, format="%.2f", key="t_amt")
            
            t_sub = st.form_submit_button("Umbuchen")
            if t_sub:
                if cat_from == cat_to:
                    st.error("Quelle und Ziel müssen unterschiedlich sein.")
                else:
                    perform_transfer(t_date, cat_from, cat_to, t_amt)
                    st.success(f"{t_amt}€ von {cat_from} nach {cat_to} verschoben.")
                    st.rerun()
        else:
            st.warning("Du brauchst mindestens 2 Kategorien für eine Umbuchung.")

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
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📅 Monatsübersicht", "📈 Verlauf", "📊 Trends", "⚖️ Vergleich", "📝 Editor"])

    # --- TAB 1: Monatsübersicht (MIT ÜBERTRAG LOGIK) ---
    with tab1:
        st.subheader("Details pro Monat")
        
        # Dropdown Optionen bauen
        month_options = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
        
        if not month_options.empty:
            selected_month_label = st.selectbox("Monat auswählen", month_options['Analyse_Monat'].unique())
            
            # Wir müssen wissen, welcher numerische Sort-Key das ist, um "Vormonate" zu berechnen
            current_sort_key = month_options[month_options['Analyse_Monat'] == selected_month_label]['sort_key_month'].iloc[0]
            
            # 1. Daten für AKTUELLEN Monat
            df_curr = df[df['sort_key_month'] == current_sort_key].copy()
            
            # 2. Daten für ALLE VORHERIGEN Monate (für Übertrag)
            df_prev = df[df['sort_key_month'] < current_sort_key].copy()
            
            # --- BERECHNUNG ÜBERTRAG (Rollover) ---
            # Summe aller SOLLs der Vergangenheit - Summe aller ISTs der Vergangenheit
            # Das ist das Geld, das noch im Umschlag liegt.
            prev_soll = df_prev[df_prev['type'] == 'SOLL'].groupby('category')['amount'].sum()
            prev_ist = df_prev[df_prev['type'] == 'IST'].groupby('category')['amount'].sum()
            carryover = prev_soll.subtract(prev_ist, fill_value=0)
            
            # --- BERECHNUNG AKTUELL ---
            curr_soll = df_curr[df_curr['type'] == 'SOLL'].groupby('category')['amount'].sum()
            curr_ist = df_curr[df_curr['type'] == 'IST'].groupby('category')['amount'].sum()
            
            # Alles zusammenführen
            overview = pd.DataFrame({
                'Übertrag Vormonat': carryover,
                'Budget (Neu)': curr_soll,
                'Ausgaben (IST)': curr_ist
            }).fillna(0)
            
            overview['Gesamt Verfügbar'] = overview['Übertrag Vormonat'] + overview['Budget (Neu)']
            overview['Rest'] = overview['Gesamt Verfügbar'] - overview['Ausgaben (IST)']
            overview['Genutzt %'] = (overview['Ausgaben (IST)'] / overview['Gesamt Verfügbar'] * 100).fillna(0)
            
            # KPIs
            c1, c2, c3, c4 = st.columns(4)
            sum_carry = overview['Übertrag Vormonat'].sum()
            sum_new = overview['Budget (Neu'].sum()
            sum_ist = overview['Ausgaben (IST)'].sum()
            sum_rest = overview['Rest'].sum()
            
            c1.metric("Übertrag (Alt)", format_euro(sum_carry), help="Geld, das aus Vormonaten übrig blieb")
            c2.metric("Frisches Budget", format_euro(sum_new), help="Geld, das diesem Monat zugewiesen wurde")
            c3.metric("Ausgaben", format_euro(sum_ist))
            c4.metric("Aktueller Rest", format_euro(sum_rest))
            
            # Tabelle
            # Styling: Übertrag grau, Budget blau, Rest fett
            st.dataframe(
                overview.style
                .format("{:.2f} €", subset=['Übertrag Vormonat', 'Budget (Neu)', 'Ausgaben (IST)', 'Gesamt Verfügbar', 'Rest'])
                .format("{:.1f} %", subset=['Genutzt %'])
                .bar(subset=['Genutzt %'], color='#ffbd45', vmin=0, vmax=100)
                .applymap(lambda v: 'color: gray', subset=['Übertrag Vormonat'])
                .applymap(lambda v: 'font-weight: bold', subset=['Rest']),
                use_container_width=True
            )
            
            st.caption("Hinweis: Wenn du 'Übertrag Vormonat' in den Notgroschen verschieben willst, nutze die Funktion 'Umbuchung' in der Sidebar.")

            with st.expander("Einzelbuchungen diesen Monat"):
                st.dataframe(df_curr[['date', 'category', 'description', 'amount', 'type']].sort_values(by='date', ascending=False).style.format({"date": lambda t: t.strftime("%d.%m.%Y"), "amount": "{:.2f} €"}), hide_index=True, use_container_width=True)

    # --- TAB 2: VERLAUF ---
    with tab2:
        st.subheader("📈 Verlauf")
        mode = st.radio("Modus", ["Monate (Tag 1-31)", "Jahre (Jan-Dez)", "Quartale"], horizontal=True)
        cat_options = ["Alle"] + sorted(current_categories)
        sel_cat = st.selectbox("Kategorie", cat_options)
        
        df_c = df[df['type'] == 'IST'].copy()
        if sel_cat != "Alle": df_c = df_c[df_c['category'] == sel_cat]
        
        x_vals, y_a, y_b, n_a, n_b = [], [], [], "", ""
        
        if "Monate" in mode:
            opts = df[['Analyse_Monat', 'sort_key_month']].drop_duplicates().sort_values('sort_key_month', ascending=False)
            all_m = opts['Analyse_Monat'].unique()
            if len(all_m) >= 1:
                c1, c2 = st.columns(2)
                with c1: n_a = st.selectbox("A", all_m, index=0)
                with c2: n_b = st.selectbox("B", all_m, index=1 if len(all_m)>1 else 0)
                
                def get_d(dframe, m_lbl):
                    # Filterung über Analyse_Monat
                    d = dframe[dframe['Analyse_Monat'] == m_lbl]
                    return d.groupby(d['date'].dt.day)['amount'].sum().reindex(range(1, 32), fill_value=0)
                
                y_a, y_b = get_d(df_c, n_a), get_d(df_c, n_b)
                x_vals = list(range(1, 32))
                
        elif "Jahre" in mode:
            ys = sorted(df['Jahr'].unique())
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
            qs = sorted(df['Quartal'].unique(), reverse=True)
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

    # --- TAB 3: Trends ---
    with tab3:
        st.subheader("Balken-Übersicht")
        vm = st.radio("Ansicht", ["Monatlich", "Quartalsweise", "Jährlich"], horizontal=True, key="tr_rad")
        if vm == "Monatlich":
            # Hier nutzen wir Analyse_Monat für die Achse
            agg = df.groupby(['sort_key_month', 'Analyse_Monat', 'type'])['amount'].sum().unstack(fill_value=0)
            agg = agg.reset_index().sort_values('sort_key_month').set_index('Analyse_Monat')
            cols = [c for c in ['SOLL', 'IST'] if c in agg.columns]
            st.bar_chart(agg[cols])
        elif vm == "Quartalsweise":
            st.bar_chart(df.groupby(['Quartal', 'type'])['amount'].sum().unstack(fill_value=0))
        else:
            st.bar_chart(df.groupby(['Jahr', 'type'])['amount'].sum().unstack(fill_value=0))

    # --- TAB 4: Vergleich ---
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
                    if t=="M": return df[df['Analyse_Monat']==v]
                    if t=="Q": return df[df['Quartal']==v]
                    if t=="J": return df[df['Jahr'].astype(str)==v]
                    return pd.DataFrame()
                d_a, d_b = fp(p1), fp(p2)
                if not d_a.empty and not d_b.empty:
                    sa, sb = d_a[d_a['type']=='IST'].groupby('category')['amount'].sum(), d_b[d_b['type']=='IST'].groupby('category')['amount'].sum()
                    cp = pd.DataFrame({'Basis': sa, 'Vgl': sb}).fillna(0)
                    cp['Diff'], cp['%'] = cp['Basis']-cp['Vgl'], cp.apply(lambda r: (r['Basis']-r['Vgl'])/r['Vgl']*100 if r['Vgl']!=0 else (100 if r['Basis']>0 else 0), axis=1)
                    st.dataframe(cp.style.format("{:.2f} €", subset=['Basis','Vgl','Diff']).format("{:+.1f} %", subset=['%']).applymap(lambda v: f'color: {"red" if v>0 else "green"}; font-weight: bold' if v!=0 else 'color:black', subset=['Diff', '%']), use_container_width=True)

    # --- TAB 5: EDITOR ---
    with tab5:
        st.subheader("📝 Daten korrigieren")
        df_ed = df.sort_values(by=['date', 'id'], ascending=[False, False]).copy()
        
        # Zeige Budget Monat im Editor, falls vorhanden
        col_conf = {
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "date": st.column_config.DateColumn("Datum", format="DD.MM.YYYY"),
            "category": st.column_config.SelectboxColumn("Kategorie", options=current_categories, required=True),
            "type": st.column_config.SelectboxColumn("Typ", options=["SOLL", "IST"], required=True),
            "amount": st.column_config.NumberColumn("Betrag (€)", format="%.2f €", min_value=0),
            "budget_month": st.column_config.TextColumn("Budget Monat (YYYY-MM)"),
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
                    c.execute("DELETE FROM transactions WHERE id = ?", (int(df_ed.iloc[idx]['id']),))
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
                    # Default Budget Monat ist Monat des Datums
                    bm = r.get("budget_month", dt.strftime("%Y-%m"))
                    c.execute("INSERT INTO transactions (date, category, description, amount, type, budget_month) VALUES (?, ?, ?, ?, ?, ?)",
                              (dt, r.get("category", "Sonstiges"), r.get("description", ""), r.get("amount", 0.0), r.get("type", "IST"), bm))
                mod = True
            
            conn.commit()
            conn.close()
            if mod:
                st.success("Gespeichert!")
                st.rerun()
