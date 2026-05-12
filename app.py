import streamlit as st
import pandas as pd
from urllib.parse import urlparse, parse_qs
from io import BytesIO
import os
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Gestión Contable | UNIVALLE", 
    page_icon="🎓", 
    layout="wide"
)

# --- ESTILOS CSS PROFESIONALES ---
st.markdown("""
<style>
    .stApp { background-color: #fdf5e6; }
    
    /* Barra Lateral Guindo Institucional */
    [data-testid="stSidebar"] { 
        background-color: #741b28 !important; 
        border-right: 2px solid #b8860b;
    }
    [data-testid="stSidebar"] div, [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {
        color: #ffffff !important;
        font-weight: 500 !important;
    }

    /* Panel de Carga de Archivos */
    [data-testid="stFileUploader"] section {
        background-color: #1a1a1a !important;
        border: 1px dashed #b8860b !important;
        border-radius: 8px !important;
    }
    [data-testid="stFileUploaderDropzone"] {
        background-color: #1a1a1a !important;
    }
    [data-testid="stFileUploader"] label, [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] div, [data-testid="stFileUploader"] svg {
        color: #e0e0e0 !important; 
        fill: #ffffff !important;
    }
    [data-testid="stFileUploader"] button {
        background-color: #741b28 !important;
        color: white !important;
        border: 1px solid #b8860b !important;
    }

    /* Estilos de Tipografía y Botones */
    .stButton > button { border-radius: 4px; font-weight: 600; text-transform: uppercase; }
    .stButton > button[kind="primary"] {
        background-color: #741b28 !important;
        color: #ffffff !important;
        border: 1px solid #b8860b !important;
        height: 3em;
    }
    h1, h2, h3 { color: #741b28; font-family: 'Times New Roman', serif; }
    
    .factura-card {
        background-color: #ffffff;
        padding: 15px;
        border-left: 5px solid #741b28;
        border-radius: 4px;
        margin-bottom: 12px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .cuf-text {
        color: #b8860b;
        font-family: monospace;
        font-weight: bold;
        font-size: 0.9em;
    }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE PERSISTENCIA ---
if 'base_siat' not in st.session_state:
    st.session_state.base_siat = None
if 'registros_finales' not in st.session_state:
    st.session_state.registros_finales = []

# --- PANEL LATERAL ---
with st.sidebar:
    logo_path = "UNIVALLE LOGO.webp"
    if os.path.exists(logo_path):
        st.image(logo_path, use_container_width=True)
    else:
        st.markdown("<h2 style='color:white; text-align:center;'>UNIVALLE</h2>", unsafe_allow_html=True)
    
    # LEYENDA ACTUALIZADA
    st.markdown("<h4 style='text-align: center;'>INSTRUMENTO DE CONTROL CONTABLE</h4>", unsafe_allow_html=True)
    st.divider()
    
    st.write("### CONFIGURACIÓN")
    archivo_csv = st.file_uploader("Vincular Base SIAT (.csv)", type=['csv'])
    
    if archivo_csv:
        try:
            df_siat = pd.read_csv(archivo_csv, sep=',', encoding='latin1', on_bad_lines='skip')
            df_siat.columns = [c.strip() for c in df_siat.columns]
            st.session_state.base_siat = df_siat
            st.success("✅ Base vinculada")
        except Exception as e:
            st.error(f"Error: {e}")
    
    st.divider()
    if st.button("🔄 Reiniciar Sesión", use_container_width=True):
        st.session_state.registros_finales = []
        st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("UNIVERSIDAD DEL VALLE S.A.")
st.subheader("Módulo Centralizado de Procesamiento de Datos Fiscales")
st.divider()

if st.session_state.base_siat is not None:
    st.markdown("### 📥 Consolidación de Registros")
    urls_raw = st.text_area("Depósito de URLs para procesamiento masivo:", height=150, placeholder="Pega aquí los enlaces para iniciar la validación...")
    
    # BOTÓN CON LEYENDA ACTUALIZADA
    if st.button("🚀 EJECUTAR PROCESAMIENTO DE DATOS", type="primary", use_container_width=True):
        links = re.findall(r'https?://[^\s]+?(?=https?://|$)', urls_raw)
        base = st.session_state.base_siat
        agregados = 0
        
        for link in links:
            try:
                link_clean = link.strip().rstrip(',').rstrip(';')
                params = parse_qs(urlparse(link_clean).query)
                cuf_extraido = params.get('cuf', [''])[0].strip()
                
                if not cuf_extraido:
                    continue

                match = base[base['CODIGO DE AUTORIZACION'] == cuf_extraido]
                
                if not match.empty:
                    item = match.iloc[0]
                    if not any(d['CUF / Autorización'] == cuf_extraido for d in st.session_state.registros_finales):
                        st.session_state.registros_finales.append({
                            "Fecha": item['FECHA DE FACTURA/DUI/DIM'],
                            "Razón Social": item['RAZON SOCIAL PROVEEDOR'],
                            "NIT": item['NIT PROVEEDOR'],
                            "Nro Factura": item['NUMERO FACTURA'],
                            "Monto (Bs)": item['IMPORTE TOTAL COMPRA'],
                            "CUF / Autorización": cuf_extraido
                        })
                        agregados += 1
            except:
                continue
        
        if agregados > 0:
            st.success(f"Procesamiento finalizado: {agregados} registros validados con éxito.")
        else:
            st.warning("No se identificaron nuevos datos para procesar en este lote.")

# --- REPORTES Y EXPORTACIÓN ---
if st.session_state.registros_finales:
    st.divider()
    st.write("### 📊 Historial de Datos Procesados")
    
    for i, reg in enumerate(st.session_state.registros_finales):
        col_data, col_del = st.columns([12, 1])
        with col_data:
            st.markdown(f"""
            <div class='factura-card'>
                <span style='color: #741b28; font-weight: bold; font-size: 1.1em;'>{reg['Razón Social']}</span><br>
                <small>Factura: {reg['Nro Factura']} | Monto: {reg['Monto (Bs)']} Bs.</small><br>
                <span class='cuf-text'>CUF: {reg['CUF / Autorización']}</span>
            </div>
            """, unsafe_allow_html=True)
        with col_del:
            st.write("") 
            if st.button("✖", key=f"del_{i}"):
                st.session_state.registros_finales.pop(i)
                st.rerun()

    st.markdown("#### Vista Previa del Informe")
    df_res = pd.DataFrame(st.session_state.registros_finales)
    st.dataframe(df_res, use_container_width=True)
    
    buff = BytesIO()
    with pd.ExcelWriter(buff, engine='openpyxl') as w:
        df_res.to_excel(w, index=False)
    
    st.download_button(
        label="📥 DESCARGAR INFORME TÉCNICO (EXCEL)",
        data=buff.getvalue(),
        file_name="Procesamiento_Datos_UNIVALLE.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    if st.session_state.base_siat is None:
        st.info("📌 Sistema operativo. Por favor, vincule la base de datos maestra para iniciar el procesamiento.")

st.markdown("<br><p style='text-align: center; color: #741b28; opacity: 0.6;'>DEPARTAMENTO DE CONTABILIDAD | UNIVALLE S.A. © 2026</p>", unsafe_allow_html=True)
