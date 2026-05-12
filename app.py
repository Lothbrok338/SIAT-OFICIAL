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
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    /* Panel de Carga de Archivos Profesional */
    [data-testid="stFileUploader"] section {
        background-color: #1a1a1a !important;
        border: 1px dashed #b8860b !important;
        border-radius: 8px !important;
        padding: 10px;
    }
    [data-testid="stFileUploaderDropzone"] {
        background-color: #1a1a1a !important;
    }
    [data-testid="stFileUploader"] label, 
    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploader"] div,
    [data-testid="stFileUploader"] svg {
        color: #e0e0e0 !important; 
        fill: #ffffff !important;
    }
    [data-testid="stFileUploader"] button {
        background-color: #741b28 !important;
        color: white !important;
        border: 1px solid #b8860b !important;
        transition: 0.3s;
    }
    [data-testid="stFileUploader"] button:hover {
        background-color: #b8860b !important;
        color: #741b28 !important;
    }

    /* Estilos de Tipografía y Botones */
    .stButton > button { border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
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
        border-right: 1px solid #eee;
        border-top: 1px solid #eee;
        border-bottom: 1px solid #eee;
        border-radius: 4px;
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE PERSISTENCIA DE DATOS ---
if 'base_siat' not in st.session_state:
    st.session_state.base_siat = None
if 'registros_finales' not in st.session_state:
    st.session_state.registros_finales = []

# --- PANEL LATERAL (SIDEBAR) ---
with st.sidebar:
    # Intento de carga de imagen institucional
    logo_path = "UNIVALLE LOGO.webp"
    if os.path.exists(logo_path):
        st.image(logo_path, use_container_width=True)
    else:
        st.markdown("<h2 style='color:white; text-align:center;'>UNIVALLE</h2>", unsafe_allow_html=True)
    
    st.markdown("<h4 style='text-align: center;'>SISTEMA DE AUDITORÍA</h4>", unsafe_allow_html=True)
    st.divider()
    
    st.write("### CONFIGURACIÓN")
    archivo_csv = st.file_uploader("Vincular Base de Datos SIAT (.csv)", type=['csv'], help="Cargue el reporte maestro de facturación del SIAT.")
    
    if archivo_csv:
        try:
            df_siat = pd.read_csv(archivo_csv, sep=',', encoding='latin1', on_bad_lines='skip')
            df_siat.columns = [c.strip() for c in df_siat.columns]
            st.session_state.base_siat = df_siat
            st.success("✅ Base de datos vinculada con éxito")
        except Exception as e:
            st.error(f"Error en la lectura: {e}")
    
    st.divider()
    if st.button("🔄 Reiniciar Aplicación", use_container_width=True):
        st.session_state.registros_finales = []
        st.rerun()

# --- INTERFAZ PRINCIPAL ---
st.title("UNIVERSIDAD DEL VALLE S.A.")
st.subheader("Módulo de Validación y Consolidación de Crédito Fiscal")
st.markdown("*Departamento de Gestión Académica y Financiera*")
st.divider()

if st.session_state.base_siat is not None:
    st.markdown("### 🔍 Procesamiento de Documentos Fiscales")
    st.caption("Pestaña de entrada: Escanee los códigos QR o pegue las URLs del SIAT.")
    
    urls_raw = st.text_area("Registro de enlaces (URLs de facturación):", height=150, placeholder="Pega aquí los enlaces para procesar...")
    
    if st.button("🚀 VALIDAR Y PROCESAR LOTE", type="primary", use_container_width=True):
        # Regex mejorada para capturar links de forma limpia
        links = re.findall(r'https?://[^\s]+?(?=https?://|$)', urls_raw)
        base = st.session_state.base_siat
        agregados = 0
        
        for link in links:
            try:
                link_clean = link.strip().rstrip(',').rstrip(';')
                params = parse_qs(urlparse(link_clean).query)
                cuf = params.get('cuf', [''])[0].strip()
                
                # Validación contra la base cargada
                match = base[base['CODIGO DE AUTORIZACION'] == cuf]
                
                if not match.empty:
                    item = match.iloc[0]
                    # Evitar duplicados en la sesión actual
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
            st.success(f"Operación exitosa: Se han consolidado {agregados} nuevos registros fiscalizados.")
        else:
            st.warning("No se identificaron coincidencias nuevas en el lote procesado.")

# --- SECCIÓN DE REPORTES ---
if st.session_state.registros_finales:
    st.divider()
    st.write("### 📊 Detalle de Registros Consolidados")
    
    for i, reg in enumerate(st.session_state.registros_finales):
        col_data, col_del = st.columns([12, 1])
        with col_data:
            st.markdown(f"""
            <div class='factura-card'>
                <span style='color: #741b28; font-weight: bold;'>{reg['Razón Social']}</span><br>
                <small style='color: #666;'>NIT: {reg['NIT']} | Factura: {reg['Nro Factura']} | <strong>Monto: {reg['Monto (Bs)']} Bs.</strong></small>
            </div>
            """, unsafe_allow_html=True)
        with col_del:
            st.write("") 
            if st.button("✖", key=f"del_{i}", help="Eliminar este registro"):
                st.session_state.registros_finales.pop(i)
                st.rerun()

    st.markdown("#### Vista Previa del Informe")
    df_res = pd.DataFrame(st.session_state.registros_finales).drop(columns=['CUF_FULL'])
    st.dataframe(df_res, use_container_width=True)
    
    # Exportación a Excel
    buff = BytesIO()
    with pd.ExcelWriter(buff, engine='openpyxl') as w:
        df_res.to_excel(w, index=False)
    
    st.download_button(
        label="📥 DESCARGAR REPORTE CONSOLIDADO (EXCEL)",
        data=buff.getvalue(),
        file_name="Reporte_Fiscal_UNIVALLE.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    if st.session_state.base_siat is None:
        st.info("📌 Sistema en espera: Por favor, inicie sesión vinculando la base de datos maestra en el panel izquierdo.")

# --- PIE DE PÁGINA ---
st.markdown("<br><br><p style='text-align: center; color: #741b28; opacity: 0.6; font-size: 0.8em;'>SISTEMA DE GESTIÓN CONTABLE INTERNA | UNIVALLE S.A. © 2026</p>", unsafe_allow_html=True)
