import streamlit as st
import pandas as pd
from urllib.parse import urlparse, parse_qs
from io import BytesIO
import os
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Sistema de Gestión Contable | UNIVALLE", 
    page_icon="🎓", 
    layout="wide"
)

# --- CSS PROFESIONAL: IDENTIDAD CORPORATIVA ---
st.markdown("""
<style>
    /* Fondo General */
    .stApp { background-color: #fdf5e6; }
    
    /* Barra Lateral Estilo Ejecutivo */
    [data-testid="stSidebar"] { 
        background-color: #741b28 !important; 
        border-right: 3px solid #b8860b;
    }
    [data-testid="stSidebar"] div, [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {
        color: #ffffff !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    /* Panel de Carga de Archivos */
    [data-testid="stFileUploader"] section {
        background-color: #1a1a1a !important;
        border: 2px dashed #b8860b !important;
        border-radius: 12px !important;
        padding: 20px;
    }
    [data-testid="stFileUploader"] label, [data-testid="stFileUploader"] small {
        color: #e0e0e0 !important;
    }
    
    /* Botones y Títulos */
    .stButton > button { 
        border-radius: 6px; 
        transition: all 0.3s;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    h1, h2, h3 { 
        color: #741b28; 
        font-family: 'Georgia', serif; 
        font-weight: 700;
    }
    
    /* Tarjetas de Reporte */
    .factura-card {
        background-color: #ffffff;
        padding: 15px;
        border-left: 8px solid #741b28;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 12px;
    }
    .metric-box {
        background-color: #741b28;
        color: white;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
        border: 2px solid #b8860b;
    }
</style>
""", unsafe_allow_html=True)

# --- LÓGICA DE PERSISTENCIA ---
if 'base_siat' not in st.session_state:
    st.session_state.base_siat = None
if 'registros_finales' not in st.session_state:
    st.session_state.registros_finales = []

# --- SIDEBAR: CONFIGURACIÓN DEL SISTEMA ---
with st.sidebar:
    # Carga de Imagen desde el repositorio
    # Cambia 'logo_univalle.png' por el nombre exacto de tu archivo (ej. UNIVALLE LOGO.webp)
    nombre_logo = "UNIVALLE LOGO.webp" 
    if os.path.exists(nombre_logo):
        st.image(nombre_logo, use_container_width=True)
    else:
        st.warning("⚠️ Logo institucional no detectado")
        
    st.markdown("### **MÓDULO DE CONFIGURACIÓN**")
    
    archivo_csv = st.file_uploader("Importar Base de Datos Fiscal (SIAT .csv)", type=['csv'])
    
    if archivo_csv:
        try:
            df_siat = pd.read_csv(archivo_csv, sep=',', encoding='latin1', on_bad_lines='skip')
            df_siat.columns = [c.strip() for c in df_siat.columns]
            st.session_state.base_siat = df_siat
            st.success("✅ Sincronización SIAT Exitosa")
        except Exception as e:
            st.error(f"Error en estructura: {e}")
            
    st.divider()
    if st.button("清 Restablecer Ciclo de Gestión", use_container_width=True):
        st.session_state.registros_finales = []
        st.rerun()

# --- CUERPO PRINCIPAL ---
st.markdown("<h1 style='text-align: center;'>UNIVERSIDAD DEL VALLE S.A.</h1>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center; color: #b8860b;'>Sistema Centralizado de Validación y Consolidación Fiscal</h4>", unsafe_allow_html=True)
st.divider()

# Sección de Entrada de Datos
if st.session_state.base_siat is not None:
    st.markdown("### 📥 Procesamiento de Comprobantes Digitales")
    st.info("Punto de control: Ingrese las URL obtenidas de los códigos QR para su validación contra el registro maestro.")
    
    urls_raw = st.text_area("Buzón de Escaneo (Pegue los enlaces aquí):", height=150, placeholder="https://siat.impuestos.gob.bo/consulta/...")
    
    col_acc, col_info = st.columns([1, 2])
    with col_acc:
        if st.button("🚀 EJECUTAR VALIDACIÓN", type="primary", use_container_width=True):
            links = re.findall(r'https?://[^\s]+?(?=https?://|$)', urls_raw)
            base = st.session_state.base_siat
            agregados = 0
            
            for link in links:
                try:
                    link_clean = link.strip().rstrip(',').rstrip(';')
                    params = parse_qs(urlparse(link_clean).query)
                    cuf = params.get('cuf', [''])[0].strip()
                    
                    # Validación contra CODIGO DE AUTORIZACION
                    match = base[base['CODIGO DE AUTORIZACION'] == cuf]
                    
                    if not match.empty:
                        item = match.iloc[0]
                        # Evitar duplicados en la sesión actual
                        if not any(d['CUF_FULL'] == cuf for d in st.session_state.registros_finales):
                            st.session_state.registros_finales.append({
                                "Fecha Emisión": item['FECHA DE FACTURA/DUI/DIM'],
                                "Proveedor / Razón Social": item['RAZON SOCIAL PROVEEDOR'],
                                "NIT Emisor": item['NIT PROVEEDOR'],
                                "Nro. Comprobante": item['NUMERO FACTURA'],
                                "Importe Total (Bs)": float(item['IMPORTE TOTAL COMPRA']),
                                "CUF_FULL": cuf
                            })
                            agregados += 1
                except:
                    continue
            
            if agregados > 0:
                st.balloons()
                st.success(f"Procesamiento Finalizado: {agregados} nuevos registros incorporados al reporte.")
            else:
                st.warning("Aviso: No se detectaron registros nuevos o válidos en el lote ingresado.")

# --- ANALÍTICA Y REPORTES ---
if st.session_state.registros_finales:
    st.divider()
    
    # Resumen Ejecutivo
    df_res = pd.DataFrame(st.session_state.registros_finales)
    total_bs = df_res["Importe Total (Bs)"].sum()
    conteo = len(df_res)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='metric-box'><strong>TOTAL REGISTROS</strong><br><span style='font-size: 24px;'>{conteo}</span></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-box'><strong>MONTO CONSOLIDADO</strong><br><span style='font-size: 24px;'>{total_bs:,.2f} Bs.</span></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-box'><strong>ESTADO DE CARGA</strong><br><span style='font-size: 24px;'>ACTIVO</span></div>", unsafe_allow_html=True)

    st.write("### 📊 Detalle Analítico de Facturación")
    
    for i, reg in enumerate(st.session_state.registros_finales):
        col_data, col_del = st.columns([11, 1])
        with col_data:
            st.markdown(f"""
            <div class='factura-card'>
                <div style='display: flex; justify-content: space-between;'>
                    <strong>{reg['Proveedor / Razón Social']}</strong>
                    <span style='color: #741b28;'><strong>{reg['Importe Total (Bs)']:,.2f} Bs.</strong></span>
                </div>
                <small>NIT: {reg['NIT Emisor']} | Factura: {reg['Nro. Comprobante']} | Fecha: {reg['Fecha Emisión']}</small>
            </div>
            """, unsafe_allow_html=True)
        with col_del:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.registros_finales.pop(i)
                st.rerun()

    # Exportación
    st.markdown("---")
    df_export = df_res.drop(columns=['CUF_FULL'])
    
    col_exp1, col_exp2 = st.columns([3, 1])
    with col_exp1:
        st.dataframe(df_export, use_container_width=True)
    with col_exp2:
        buff = BytesIO()
        with pd.ExcelWriter(buff, engine='openpyxl') as w:
            df_export.to_excel(w, index=False)
        
        st.download_button(
            label="📥 DESCARGAR REPORTE EXCEL",
            data=buff.getvalue(),
            file_name="Reporte_Consolidado_Univalle.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
else:
    if st.session_state.base_siat is None:
        st.info("📌 **Protocolo de inicio:** Por favor, cargue la base de datos maestra (.csv) en el panel izquierdo para habilitar las funciones de validación.")

st.markdown("<br><p style='text-align: center; color: #741b28; opacity: 0.6; font-size: 12px;'>DEPARTAMENTO DE GESTIÓN CONTABLE - UNIVALLE S.A. © 2026</p>", unsafe_allow_html=True)
```
