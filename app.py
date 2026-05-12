import streamlit as st
import pandas as pd
from urllib.parse import urlparse, parse_qs
from io import BytesIO
import os
import re
 
# Configuración de página
st.set_page_config(page_title="Gestión Contable | UNIVALLE", page_icon="🎓", layout="wide")
 
# --- CSS DEFINITIVO: ALTO CONTRASTE ---
st.markdown("""
<style>
    .stApp { background-color: #fdf5e6; }
    /* Barra Lateral Guindo */
    [data-testid="stSidebar"] { background-color: #741b28 !important; }
    [data-testid="stSidebar"] div, [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
 
    /* PANEL DE CARGA NEGRO - CORRECCIÓN DE VISIBILIDAD */
    [data-testid="stFileUploader"] section {
        background-color: #000000 !important;
        border: 2px solid #b8860b !important;
        border-radius: 10px !important;
    }
    /* Forzar fondo negro y TEXTO BLANCO para que se lea 'Browse files' y 'Upload' */
    [data-testid="stFileUploaderDropzone"] {
        background-color: #000000 !important;
    }
 
    /* Aquí corregimos lo que te chocaba: Texto e íconos en blanco/dorado */
    [data-testid="stFileUploader"] label, 
    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] div,
    [data-testid="stFileUploader"] svg {
        color: #ffffff !important; 
        fill: #ffffff !important;
    }
    /* El botón pequeño que dice 'Browse files' */
    [data-testid="stFileUploader"] button {
        background-color: #333333 !important;
        color: white !important;
        border: 1px solid #b8860b !important;
    }
 
    /* Nombre del archivo cargado en Dorado para que destaque */
    [data-testid="stFileUploaderFileName"] {
        color: #b8860b !important;
    }
 
    /* Estilos Generales */
    .stButton > button { border-radius: 8px; font-weight: bold; }
    .stButton > button[kind="primary"] {
        background-color: #741b28 !important;
        color: #fdf5e6 !important;
        border: 2px solid #b8860b !important;
        height: 3.5em;
    }
    h1, h2, h3 { color: #741b28; font-family: 'Times New Roman', serif; }
    .factura-card {
        background-color: white;
        padding: 12px;
        border-left: 6px solid #741b28;
        border-radius: 4px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
</style>
    """, unsafe_allow_html=True)
 
# --- LÓGICA DE SESIÓN ---
if 'base_siat' not in st.session_state:
    st.session_state.base_siat = None
if 'registros_finales' not in st.session_state:
    st.session_state.registros_finales = []
 
# --- SIDEBAR ---
with st.sidebar:
    nombre_logo = "UNIVALLE LOGO.webp"
    if os.path.exists(nombre_logo):
        st.image(nombre_logo, use_container_width=True)
    st.markdown("---")
    st.write("### PANEL DE CONTROL")
    archivo_csv = st.file_uploader("Cargar base de datos (.csv)", type=['csv'])
    if archivo_csv:
        try:
            df_siat = pd.read_csv(archivo_csv, sep=',', encoding='latin1', on_bad_lines='skip')
            df_siat.columns = [c.strip() for c in df_siat.columns]
            st.session_state.base_siat = df_siat
            st.success("✅ Base vinculada")
        except Exception as e:
            st.error(f"Error: {e}")
    st.divider()
    if st.button("🗑️ Limpiar sesión", use_container_width=True):
        st.session_state.registros_finales = []
        st.rerun()
 
# --- CUERPO PRINCIPAL ---
st.title("UNIVERSIDAD DEL VALLE S.A.")
st.subheader("Validación y Consolidación de Facturas")
st.divider()
 
if st.session_state.base_siat is not None:
    st.markdown("### 📥 Escaneo Masivo")
    urls_raw = st.text_area("Escanea o pega los links aquí:", height=150)
    if st.button("🚀 VALIDAR LOTE", type="primary", use_container_width=True):
        links = re.findall(r'https?://[^\s]+?(?=https?://|$)', urls_raw)
        base = st.session_state.base_siat
        agregados = 0
        for link in links:
            try:
                link_clean = link.strip().rstrip(',').rstrip(';')
                params = parse_qs(urlparse(link_clean).query)
                cuf = params.get('cuf', [''])[0].strip()
                match = base[base['CODIGO DE AUTORIZACION'] == cuf]
                if not match.empty:
                    item = match.iloc[0]
                    if not any(d['CUF_FULL'] == cuf for d in st.session_state.registros_finales):
                        st.session_state.registros_finales.append({
                            "Fecha": item['FECHA DE FACTURA/DUI/DIM'],
                            "Razón Social": item['RAZON SOCIAL PROVEEDOR'],
                            "NIT": item['NIT PROVEEDOR'],
                            "Nro Factura": item['NUMERO FACTURA'],
                            "Monto (Bs)": item['IMPORTE TOTAL COMPRA'],
                            "CUF_FULL": cuf
                        })
                        agregados += 1
            except:
                continue
        if agregados > 0:
            st.success(f"Se añadieron {agregados} registros.")
        else:
            st.warning("No se encontraron facturas nuevas.")
 
# --- REPORTE ---
if st.session_state.registros_finales:
    st.divider()
    st.write("### 📊 Reporte Generado")
    for i, reg in enumerate(st.session_state.registros_finales):
        col_data, col_del = st.columns([9, 1])
        with col_data:
            st.markdown(f"""
<div class='factura-card'>
<strong>{reg['Razón Social']}</strong> | 
<small>Factura: {reg['Nro Factura']} | Monto: {reg['Monto (Bs)']} Bs.</small>
</div>
            """, unsafe_allow_html=True)
        with col_del:
            st.write("") 
            if st.button("X", key=f"del_{i}"):
                st.session_state.registros_finales.pop(i)
                st.rerun()
 
    st.markdown("---")
    df_res = pd.DataFrame(st.session_state.registros_finales).drop(columns=['CUF_FULL'])
    st.dataframe(df_res, use_container_width=True)
    buff = BytesIO()
    with pd.ExcelWriter(buff, engine='openpyxl') as w:
        df_res.to_excel(w, index=False)
    st.download_button(
        label="📥 DESCARGAR EXCEL",
        data=buff.getvalue(),
        file_name="Reporte_Univalle.xlsx",
        use_container_width=True
    )
else:
    if st.session_state.base_siat is None:
        st.info("💡 Por favor, carga la base de datos en el panel lateral para comenzar.")
 
st.markdown("<br><p style='text-align: center; color: #741b28; opacity: 0.7;'>UNIVALLE S.A. © 2026</p>", unsafe_allow_html=True)
