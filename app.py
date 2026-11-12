import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
from io import BytesIO
from PIL import Image as PILImage, ImageOps
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as PDFImage, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader
from xml.sax.saxutils import escape


def crear_comprobante_pdf(tipo, campos, foto_bytes):
    """Genera un PDF en memoria; no escribe ni envía datos a Supabase."""
    salida = BytesIO()
    documento = SimpleDocTemplate(salida, pagesize=(595, 842), rightMargin=45,
                                  leftMargin=45, topMargin=42, bottomMargin=42)
    estilos = getSampleStyleSheet()
    estilos['Title'].alignment = TA_CENTER
    contenido = [Paragraph('CONTROL VEHICULAR ACAPOMIL', estilos['Title']),
                 Spacer(1, 10), Paragraph(escape(tipo), estilos['Heading2']),
                 Spacer(1, 10)]
    filas = []
    for nombre, valor in campos.items():
        filas.append([Paragraph(escape(str(nombre)), estilos['BodyText']),
                      Paragraph(escape(str(valor if valor is not None else '')), estilos['BodyText'])])
    tabla = Table(filas, colWidths=[150, 350], hAlign='LEFT')
    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('LINEBELOW', (0, -1), (-1, -1), 0.6, colors.grey),
    ]))
    contenido += [tabla, Spacer(1, 18), Paragraph('Evidencia fotográfica', estilos['Heading3'])]
    imagen = PILImage.open(BytesIO(foto_bytes))
    imagen = ImageOps.exif_transpose(imagen).convert('RGB')
    imagen.thumbnail((1200, 1200))
    imagen_buffer = BytesIO()
    imagen.save(imagen_buffer, format='JPEG', quality=85)
    imagen_buffer.seek(0)
    ancho, alto = imagen.size
    escala = min(470 / ancho, 310 / alto)
    contenido.append(PDFImage(imagen_buffer, width=ancho * escala, height=alto * escala))
    contenido += [Spacer(1, 14), Paragraph(
        'Comprobante generado localmente. No constituye un registro oficial de acceso '
        'ni acredita almacenamiento en Supabase.', estilos['Italic'])]
    documento.build(contenido)
    return salida.getvalue()


st.set_page_config(page_title="Control Vehicular ACAPOMIL", layout="wide")
st.title("🚗 Control Vehicular ACAPOMIL")
st.sidebar.title("🚗 ACAPOMIL")
perfil = st.sidebar.radio("Seleccione un módulo", ["Guardia", "Conductor", "Administrador"])
st.sidebar.divider()
st.sidebar.info("Sistema de Control Vehicular ACAPOMIL")
st.sidebar.caption("Modo de consulta y simulación: no se guardan cambios en Supabase.")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"No fue posible configurar la conexión: {e}")
    st.stop()


def consultar(tabla, orden=None):
    consulta = supabase.table(tabla).select("*")
    if orden:
        consulta = consulta.order(orden)
    return consulta.execute().data or []


if perfil == "Guardia":
    st.header("🛡️ Control de acceso - Guardia")
    st.info("Verificación de autorizaciones. Esta consulta no registra accesos.")
    try:
        vehiculos = consultar("vehiculos", "patente")
        conductores = consultar("conductores", "nombre_completo")
        if not vehiculos or not conductores:
            st.warning("No hay vehículos o conductores disponibles.")
        else:
            patentes = [v["patente"] for v in vehiculos]
            patente = st.selectbox("Seleccione la patente", patentes)
            opciones = {f'{c["nombre_completo"]} - {c["rut"]}': c["rut"] for c in conductores}
            conductor = st.selectbox("Seleccione el conductor", list(opciones))
            st.subheader("📷 Fotografía comprobatoria")
            metodo_foto = st.radio(
                "¿Cómo deseas ingresar la fotografía?",
                ["Tomar fotografía", "Subir fotografía"],
                horizontal=True,
                key="metodo_foto_guardia",
            )
            if metodo_foto == "Tomar fotografía":
                foto = st.camera_input("Fotografía del vehículo o patente", key="camara_guardia")
            else:
                foto = st.file_uploader(
                    "Selecciona una imagen JPG o PNG",
                    type=["jpg", "jpeg", "png"],
                    key="archivo_guardia",
                )

            if foto is not None:
                st.image(foto, caption="Fotografía comprobatoria (vista previa)", width=350)
                st.success("Fotografía cargada para esta verificación.")

            if st.button("Verificar autorización", type="primary"):
                st.session_state.pop("pdf_guardia", None)
                if foto is None:
                    st.warning("Debes tomar o subir una fotografía antes de verificar el acceso.")
                else:
                    rut = opciones[conductor]
                    vehiculo = next(v for v in vehiculos if v["patente"] == patente)
                    persona = next(c for c in conductores if c["rut"] == rut)
                    autorizaciones = (
                        supabase.table("autorizaciones")
                        .select("id")
                        .eq("patente", patente)
                        .eq("rut_conductor", rut)
                        .eq("vigente", True)
                        .execute()
                        .data or []
                    )
                    if persona["estado"] != "Activo":
                        resultado_guardia = "DENEGADO - Conductor inactivo"
                        st.error("ACCESO DENEGADO: conductor inactivo")
                    elif not autorizaciones:
                        resultado_guardia = "DENEGADO - Sin autorización vigente"
                        st.error("ACCESO DENEGADO: sin autorización vigente")
                    elif vehiculo["estado_operativo"] != "Operativo":
                        resultado_guardia = "ALERTA DE ESTADO - Vehículo no operativo"
                        st.warning("ALERTA: vehículo no está operativo")
                    else:
                        resultado_guardia = "AUTORIZADO"
                        st.success("ACCESO AUTORIZADO")
                    fecha_guardia = datetime.now().astimezone().strftime("%d-%m-%Y %H:%M:%S")
                    st.session_state["pdf_guardia"] = crear_comprobante_pdf(
                        "Comprobante de verificación - Guardia",
                        {"Fecha y hora (equipo local)": fecha_guardia,
                         "Patente": patente,
                         "Conductor": persona["nombre_completo"],
                         "RUT": rut,
                         "Vehículo": vehiculo["marca_modelo"],
                         "Estado del vehículo": vehiculo["estado_operativo"],
                         "Resultado": resultado_guardia},
                        foto.getvalue(),
                    )
                    st.session_state["nombre_pdf_guardia"] = f"guardia_{patente}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    st.write("**Conductor:**", persona["nombre_completo"])
                    st.write("**Vehículo:**", vehiculo["marca_modelo"])
                    st.write("**Patente:**", patente)
                    st.write("**Estado:**", vehiculo["estado_operativo"])
                    st.info("La fotografía se usa solo como vista previa en esta sesión; no se guarda en Supabase ni en un historial.")
        if st.session_state.get("pdf_guardia"):
            st.download_button(
                "📄 Descargar comprobante de Guardia (PDF)",
                data=st.session_state["pdf_guardia"],
                file_name=st.session_state.get("nombre_pdf_guardia", "comprobante_guardia.pdf"),
                mime="application/pdf",
                key="descarga_pdf_guardia",
            )
    except Exception as e:
        st.error(f"Error en módulo Guardia: {e}")

elif perfil == "Conductor":
    st.header("🚙 Módulo Conductor - Reporte Operativo")
    st.info("Simulación local: los datos ingresados no se envían a Supabase.")
    try:
        vehiculos = consultar("vehiculos", "patente")
        conductores = [c for c in consultar("conductores", "nombre_completo") if c["estado"] == "Activo"]
        if not vehiculos or not conductores:
            st.warning("No hay vehículos o conductores disponibles.")
        else:
            st.subheader("📷 Fotografía de evidencia mecánica")
            metodo_foto_conductor = st.radio(
                "¿Cómo deseas ingresar la fotografía?",
                ["Tomar fotografía", "Subir fotografía"],
                horizontal=True,
                key="metodo_foto_conductor",
            )
            if metodo_foto_conductor == "Tomar fotografía":
                foto_conductor = st.camera_input(
                    "Fotografía del vehículo o de la falla",
                    key="camara_conductor",
                )
            else:
                foto_conductor = st.file_uploader(
                    "Selecciona una imagen JPG o PNG",
                    type=["jpg", "jpeg", "png"],
                    key="archivo_conductor",
                )
            if foto_conductor is not None:
                st.image(foto_conductor, caption="Evidencia mecánica (vista previa)", width=350)
                st.success("Fotografía cargada para esta evaluación.")

            with st.form("formulario_conductor"):
                patente = st.selectbox("Seleccione la patente", [v["patente"] for v in vehiculos])
                conductor = st.selectbox("Seleccione el conductor", [f'{c["nombre_completo"]} - {c["rut"]}' for c in conductores])
                kilometraje = st.number_input("Kilometraje actual", min_value=0, step=1)
                combustible = st.slider("Nivel de combustible (%)", 0, 100, 50)
                neumaticos = st.radio("Presión de neumáticos", ["Correcta", "Baja presión"])
                luces = st.radio("Estado de las luces", ["Operativas", "Falla"])
                observaciones = st.text_area("Observaciones mecánicas")
                enviar = st.form_submit_button("Evaluar estado del vehículo")

            if enviar:
                st.session_state.pop("pdf_conductor", None)
            if enviar and foto_conductor is None:
                st.warning("Debes tomar o subir una fotografía antes de evaluar el reporte.")
            if enviar and foto_conductor is not None:
                st.subheader("Resultado de la evaluación")
                st.write("**Patente:**", patente)
                st.write("**Conductor:**", conductor)
                st.write("**Kilometraje:**", kilometraje)
                st.write("**Combustible:**", f"{combustible}%")
                st.write("**Observaciones:**", observaciones or "Sin observaciones")
                observacion_normalizada = observaciones.upper()
                falla_critica = any(x in observacion_normalizada for x in ["CRÍTICO:FRENOS", "CRITICO:FRENOS", "FALLA DE FRENOS"])
                if falla_critica:
                    resultado_conductor = "ALERTA CRÍTICA - Posible falla de frenos"
                    st.error("🚨 ALERTA CRÍTICA: posible falla de frenos reportada.")
                elif neumaticos == "Baja presión" or luces == "Falla":
                    resultado_conductor = "ALERTA - Requiere revisión o mantención"
                    st.error("ALERTA: vehículo requiere revisión o mantención.")
                else:
                    resultado_conductor = "Sin fallas detectadas en los parámetros evaluados"
                    st.success("Sin fallas detectadas en los parámetros evaluados.")
                fecha_conductor = datetime.now().astimezone().strftime("%d-%m-%Y %H:%M:%S")
                st.session_state["pdf_conductor"] = crear_comprobante_pdf(
                    "Comprobante de evaluación - Conductor",
                    {"Fecha y hora (equipo local)": fecha_conductor,
                     "Patente": patente,
                     "Conductor": conductor,
                     "Kilometraje declarado": kilometraje,
                     "Combustible": f"{combustible}%",
                     "Neumáticos": neumaticos,
                     "Luces": luces,
                     "Observaciones": observaciones or "Sin observaciones",
                     "Resultado": resultado_conductor},
                    foto_conductor.getvalue(),
                )
                st.session_state["nombre_pdf_conductor"] = f"conductor_{patente}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                st.info("Evaluación de prueba: la fotografía y los datos no se guardan en Supabase.")
            if st.session_state.get("pdf_conductor"):
                st.download_button(
                    "📄 Descargar comprobante del Conductor (PDF)",
                    data=st.session_state["pdf_conductor"],
                    file_name=st.session_state.get("nombre_pdf_conductor", "comprobante_conductor.pdf"),
                    mime="application/pdf",
                    key="descarga_pdf_conductor",
                )
    except Exception as e:
        st.error(f"Error en módulo Conductor: {e}")

elif perfil == "Administrador":
    st.header("📊 Dashboard Administrador - ACAPOMIL")
    try:
        vehiculos = consultar("vehiculos", "patente")
        if not vehiculos:
            st.warning("No hay vehículos registrados.")
        else:
            df = pd.DataFrame(vehiculos)
            total = len(df)
            operativos = int((df["estado_operativo"] == "Operativo").sum())
            mantencion = int((df["estado_operativo"] == "Requiere Mantención").sum())
            criticos = int((df["estado_operativo"] == "Crítico").sum())
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total vehículos", total)
            col2.metric("Disponibilidad", f"{100 * operativos / total:.1f}%")
            col3.metric("Requieren mantención", mantencion)
            col4.metric("Vehículos críticos", criticos)
            st.subheader("🚦 Estado de la flota")
            df["Semáforo"] = df["estado_operativo"].map({"Operativo": "🟢", "Requiere Mantención": "🟡", "Crítico": "🔴"}).fillna("⚪")
            st.dataframe(df[["Semáforo", "patente", "marca_modelo", "tipo_vehiculo", "kilometraje_actual", "estado_operativo"]], use_container_width=True, hide_index=True)
            st.subheader("Distribución de estados")
            st.plotly_chart(px.pie(df, names="estado_operativo", title="Estado operacional de vehículos", hole=0.4), use_container_width=True)
            st.subheader("Kilometraje por vehículo")
            st.plotly_chart(px.bar(df, x="patente", y="kilometraje_actual", color="estado_operativo", title="Kilometraje acumulado de la flota"), use_container_width=True)
            st.subheader("🔎 Consulta de vehículo")
            patente = st.selectbox("Seleccione una patente", df["patente"].tolist(), key="patente_admin")
            seleccionado = df[df["patente"] == patente].iloc[0]
            st.write("**Modelo:**", seleccionado["marca_modelo"])
            st.write("**Tipo:**", seleccionado["tipo_vehiculo"])
            st.write("**Año:**", seleccionado["anio"])
            st.write("**Kilometraje:**", seleccionado["kilometraje_actual"])
            st.write("**Estado:**", seleccionado["estado_operativo"])
    except Exception as e:
        st.error(f"Error en dashboard: {e}")

    st.divider()
    st.header("📋 Bitácora de reportes vehiculares")
    try:
        reportes = (supabase.table("reportes_estado").select("*")
                    .order("fecha_reporte", desc=True).execute().data or [])
        if not reportes:
            st.info("No existen reportes registrados.")
        else:
            df_reportes = pd.DataFrame(reportes)
            st.success(f"Se encontraron {len(df_reportes)} reportes")
            patentes = sorted(df_reportes["patente"].dropna().unique().tolist())
            patente = st.selectbox("Seleccione una patente", patentes, key="patente_bitacora")
            historial = df_reportes[df_reportes["patente"] == patente]
            st.subheader("Historial del vehículo")
            st.dataframe(historial, use_container_width=True, hide_index=True)
            for _, reporte in historial.iterrows():
                with st.expander(f"Reporte: {reporte['fecha_reporte']}"):
                    st.write("**Patente:**", reporte["patente"])
                    st.write("**Conductor:**", reporte["rut_conductor"])
                    st.write("**Kilometraje:**", reporte["kilometraje_salida"])
                    st.write("**Combustible:**", f"{reporte['nivel_combustible']}%")
                    st.success("Neumáticos: correctos") if reporte["presion_neumaticos"] else st.error("Neumáticos: baja presión")
                    st.success("Luces: operativas") if reporte["luces_operativas"] else st.error("Luces: falla detectada")
                    observaciones = str(reporte.get("observaciones") or "")
                    st.write("**Observaciones:**", observaciones or "Sin observaciones")
                    if any(x in observaciones.upper() for x in ["CRÍTICO:FRENOS", "CRITICO:FRENOS", "FALLA DE FRENOS"]):
                        st.error("🚨 ALERTA CRÍTICA: se reportó una falla de frenos.")
                    foto = reporte.get("foto_evidencia_url")
                    if isinstance(foto, str) and foto:
                        if foto.startswith(("https://", "http://")):
                            st.caption("Fotografía registrada (su visualización depende de los permisos de Storage).")
                            st.image(foto, width=350)
                        else:
                            st.info("La fotografía está referenciada en Storage privado y requiere acceso autorizado para visualizarse.")
    except Exception as e:
        st.error(f"Error al consultar bitácora: {e}")

    st.caption("Historial de accesos no disponible: la tabla registros_acceso no existe en la base consultada.")
