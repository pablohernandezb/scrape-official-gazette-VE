"""
Extract government changes from Venezuelan Official Gazette PDFs.
Processes all Ordinaria and Extraordinaria gazettes and outputs a CSV database.
"""

import argparse
import fitz
import csv
import os
import re


def extract_text(pdf_path):
    """Extract full text from a PDF."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    # Fix PDF ligature encoding: chr(191) = '¿' is used for 'fi' ligature in some PDFs
    # Only replace when ¿ appears inside a word (between letters), not standalone
    text = re.sub(r'(?<=[a-záéíóúñüA-ZÁÉÍÓÚÑÜ])\u00bf(?=[a-záéíóúñüA-ZÁÉÍÓÚÑÜ])', 'fi', text)
    return text


def extract_date(text):
    """Extract gazette date from text."""
    pattern = r"Caracas,\s+\w+\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})"
    m = re.search(pattern, text)
    if m:
        day, month_str, year = m.group(1), m.group(2).lower(), m.group(3)
        months = {
            "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
            "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
            "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
        }
        month = months.get(month_str, "00")
        return f"{year}-{month}-{day.zfill(2)}"
    return ""


def collapse_ws(text):
    """Collapse whitespace to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


# ─── Military detection ─────────────────────────────────────────────

MILITARY_RANK_PATTERNS = [
    r"General\s+en\s+Jefe", r"Almirante\s+en\s+Jefe",
    r"Mayor\s+General", r"Vicealmirante",
    r"General\s+de\s+Divisi[oó]n", r"Contralmirante",
    r"General\s+de\s+Brigada", r"Capit[aá]n\s+de\s+Nav[ií]o",
    r"Coronel(?!\s+Mora)", r"Capit[aá]n\s+de\s+Fragata",
    r"Teniente\s+Coronel", r"Capit[aá]n\s+de\s+Corbeta",
]

MILITARY_INSTITUTIONS_KW = [
    "fuerza armada nacional bolivariana", "fanb",
    "ministerio del poder popular para la defensa",
    "guardia nacional", "guardia de honor presidencial",
    "milicia", "ceofanb", "comando estrat", "sedefanb",
    "brigada de fuerzas especiales", "grupo aéreo presidencial",
    "unidad especial de seguridad", "brigada especial de protecci",
    "comando de la aviaci", "armada bolivariana",
]


def is_military_person(text):
    for pat in MILITARY_RANK_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def is_military_post(text):
    t = text.lower()
    return any(kw in t for kw in MILITARY_INSTITUTIONS_KW)


def extract_military_rank(text):
    for pat in MILITARY_RANK_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


# ─── Classification ─────────────────────────────────────────────────

def classify_change(text):
    """Classify the type of government change from summary text."""
    t = text.lower()

    # States of exception / emergency
    if "estado de conmoci" in t or "estado de excepci" in t:
        return "ESTADO_DE_EXCEPCION"
    if "duelo nacional" in t:
        return "DUELO_NACIONAL"

    # Legislative
    if "ley de amnist" in t:
        return "LEY_AMNISTIA"
    if "reforma" in t and "ley" in t:
        return "REFORMA_LEGISLATIVA"

    # Institutional restructuring
    if ("supresi" in t and "ministerio" in t) or ("se ordena la supresi" in t and "ministerio" in t):
        return "SUPRESION_MINISTERIO"
    if "se crea" in t and "ministerio" in t:
        return "CREACION_MINISTERIO"
    if "reorganizaci" in t:
        return "REORGANIZACION_INSTITUCIONAL"
    if "restructuraci" in t or "reestructuraci" in t:
        return "REESTRUCTURACION"
    if "se crea" in t and "despacho" in t and "viceministr" in t:
        return "CREACION_VICEMINISTERIO"
    if "se crea" in t and ("despacho" in t or "viceministerio" in t):
        return "CREACION_VICEMINISTERIO"
    if "supresi" in t and "liquidaci" in t:
        return "SUPRESION_ENTE"
    if "fusi" in t and ("unidad" in t or "divisi" in t):
        return "FUSION_UNIDADES"
    if "transfi" in t and ("ejecuci" in t or "competencia" in t or "fines" in t):
        return "TRANSFERENCIA_COMPETENCIAS"

    # Decorations / honors
    if "orden francisco de miranda" in t or "condecoraci" in t:
        return "CONDECORACION"
    if "medalla" in t and "orden al m" in t:
        return "CONDECORACION"
    if "premio nacional" in t:
        return "PREMIO_NACIONAL"

    # Elections (Asamblea Nacional directive)
    if "elige" in t and "asamblea nacional" in t:
        return "ELECCION_DIRECTIVA_AN"
    if "representante" in t and "asamblea nacional" in t and "consejo de estado" in t:
        return "DESIGNACION_REPRESENTANTE_AN"

    # Homage
    if "homenaje" in t or "m\u00e1rtires" in t or "martires" in t:
        return "ACUERDO_HOMENAJE"

    # Budget structures — check BEFORE designations (entries mention "designación de funcionarios")
    if ("estructura financiera" in t or "estructura para la ejecuci" in t) and "presupuesto" in t:
        return "ESTRUCTURA_PRESUPUESTARIA"

    # Designations — specific to general
    if ("nombra" in t or "nombro" in t or "designa" in t):
        if re.search(r"como\s+vicepresidente?a?\s+sectorial", t):
            return "DESIGNACION_VICEPRESIDENTE_SECTORIAL"
        if re.search(r"como\s+viceministr[oa]", t):
            return "DESIGNACION_VICEMINISTRO"
        # Only classify as MINISTRO if the person IS the minister, not just within a ministry
        if re.search(r"como\s+ministr[oa]", t):
            return "DESIGNACION_MINISTRO"
        if "embajad" in t:
            return "DESIGNACION_DIPLOMATICA"
        if re.search(r"c[oó]nsul", t):
            return "DESIGNACION_DIPLOMATICA"
        if "president" in t and any(kw in t for kw in [
            "fundaci", "instituto", "corporaci", "empresa", "sociedad",
            "c.a", "s.a", "seniat", "inatur", "inpsasel", "inac", "inapymi",
            "conviasa", "corpoelec", "metro", "centro nacional", "consejo nacional",
            "radio", "televisi", "agencia", "fondo", "complejo",
        ]):
            return "DESIGNACION_PRESIDENTE_ENTE"
        if "rector" in t and ("universidad" in t or "ucs" in t):
            return "DESIGNACION_RECTOR"
        if "junta" in t and ("administradora" in t or "interventora" in t or "directiva" in t):
            return "DESIGNACION_JUNTA"
        if "director general" in t or "directora general" in t:
            return "DESIGNACION_DIRECTOR_GENERAL"
        if "director" in t or "directora" in t:
            return "DESIGNACION_DIRECTOR"
        if "fiscal" in t and "provisori" in t:
            return "DESIGNACION_FISCAL"
        if "fiscal" in t and "auxiliar" in t:
            return "DESIGNACION_FISCAL"
        if "fiscal" in t:
            return "DESIGNACION_FISCAL"
        if "gerente" in t:
            return "DESIGNACION_GERENTE"
        if "auditor" in t:
            return "DESIGNACION_AUDITOR"
        if "administrador" in t or "administradora" in t or "cuentadante" in t:
            return "DESIGNACION_ADMINISTRADOR"
        if "inspector" in t:
            return "DESIGNACION_INSPECTOR"
        if "comisionad" in t:
            return "DESIGNACION_COMISIONADO"
        if "autoridad" in t and "salud" in t:
            return "DESIGNACION_AUTORIDAD_SALUD"
        if "jefe" in t and "divisi" in t:
            return "DESIGNACION_JEFE_DIVISION"
        if "comandante" in t or "comando" in t:
            return "DESIGNACION_COMANDANTE"
        if "contralor" in t:
            return "DESIGNACION_CONTRALOR"
        if "superintend" in t or "intendent" in t:
            return "DESIGNACION_SUPERINTENDENTE"
        if "defensor" in t and "pueblo" in t:
            return "DESIGNACION_DEFENSOR_PUEBLO"
        if "coordinador" in t or "coordinadora" in t:
            return "DESIGNACION_COORDINADOR"
        if "responsable patrimonial" in t or "responsable del manejo" in t:
            return "DESIGNACION_ADMINISTRADOR"
        if "representante" in t:
            return "DESIGNACION_REPRESENTANTE"
        if re.search(r"capit[aá]n\s+de\s+puerto", t):
            return "DESIGNACION_CAPITAN_PUERTO"
        return "DESIGNACION_OTRO"

    # Transfers (fiscales)
    if "traslad" in t and "fiscal" in t:
        return "TRASLADO_FISCAL"
    if "traslad" in t and ("subdirector" in t or "investigaci" in t):
        return "TRASLADO_FUNCIONARIO"

    # Junta designations (without "nombra/designa" keyword)
    if "junta administradora" in t or "junta interventora" in t or "junta directiva" in t:
        return "DESIGNACION_JUNTA"

    # Jubilations / pensions
    if "jubilaci" in t:
        return "JUBILACION"
    if "pensi" in t and ("sobreviviente" in t or "incapacidad" in t):
        return "PENSION"

    # Delegations
    if "delega" in t and ("firma" in t or "atribucion" in t or "funciones" in t or "facultad" in t or "aprobaci" in t or "pagos" in t):
        return "DELEGACION_FUNCIONES"
    if "delega" in t and ("intendent" in t or "superintend" in t):
        return "DELEGACION_FUNCIONES"

    # Education
    if "programa nacional de formaci" in t or "redise" in t:
        return "PROGRAMA_EDUCATIVO"
    if "autoriza" in t and ("universidad" in t or "instituto universitario" in t or "extensi" in t or "educaci" in t):
        return "AUTORIZACION_UNIVERSITARIA"
    if "aprueba" in t and ("carrera" in t or "menci" in t):
        return "AUTORIZACION_UNIVERSITARIA"
    if ("autoriza" in t or "funcionamiento" in t) and "instituci" in t and "educaci" in t:
        return "AUTORIZACION_UNIVERSITARIA"

    # Fiscal / Budget — check this BEFORE designations to catch budget structures
    if ("estructura financiera" in t or "estructura para la ejecuci" in t) and "presupuesto" in t:
        return "ESTRUCTURA_PRESUPUESTARIA"
    if "exonera" in t and ("impuesto" in t or "tasa" in t):
        return "EXONERACION_FISCAL"
    if "tasa" in t and "inter" in t and ("moratori" in t or "aplicable" in t):
        return "REGULACION_TASAS"

    # Norms / Standards
    if "norma venezolana covenin" in t or "norma covenin" in t:
        return "NORMA_TECNICA"
    if "reglamento" in t:
        return "REGLAMENTO"
    if "lineamientos" in t:
        return "LINEAMIENTOS"

    # Commissions
    if "comisi" in t and "contratacion" in t:
        return "COMISION_CONTRATACIONES"
    if "comit" in t and "licitacion" in t:
        return "COMITE_LICITACIONES"

    # Revocations / corrections
    if "revoca" in t:
        return "REVOCACION"
    if "corrige" in t and "error material" in t:
        return "CORRECCION_ERROR"
    if "deja sin efecto" in t:
        return "REVOCACION"

    # Certifications / authorizations
    if "certificado" in t and ("funcionamiento" in t or "operaciones" in t):
        return "CERTIFICACION"
    if "permiso operacional" in t:
        return "PERMISO_OPERACIONAL"
    if "acreditaci" in t:
        return "ACREDITACION"

    # Property / real estate
    if "compra" in t and ("residencia" in t or "embajada" in t):
        return "ADQUISICION_INMUEBLE"
    if "reubicaci" in t and "sede" in t:
        return "REUBICACION_SEDE"

    # Convocations
    if "convoca" in t:
        return "CONVOCATORIA"

    # Lists of entities
    if "lista de los entes" in t or "entes descentralizados" in t:
        return "LISTADO_ENTES"

    # Prórrogas
    if "prorroga" in t:
        return "PRORROGA"

    # Sistema hídrico / restructuraciones especiales
    if "sistema h" in t and "drico" in t:
        return "REESTRUCTURACION"

    # Estudios comparativos (BCV)
    if "estudio comparativo" in t:
        return "PUBLICACION_BCV"

    # Ampliación de carreras
    if "ampl" in t and ("carrera" in t or "licenciatura" in t):
        return "AUTORIZACION_UNIVERSITARIA"

    # Cease of interim positions
    if "cesa" in t and "encargadur" in t:
        return "CESE_ENCARGADURIA"

    # Normas internas
    if "normas" in t and ("sistema interno" in t or "modificaciones presupuestarias" in t):
        return "NORMA_INTERNA"

    # Autorizaciones aduanales
    if "autoriza" in t and ("aduan" in t or "agencia" in t):
        return "AUTORIZACION_ADUANAL"

    # Estaciones / aprobaciones aeronáuticas
    if "aprueba" in t and ("estaci" in t or "aeropuerto" in t):
        return "APROBACION_AERONAUTICA"

    return "OTRO"


# ─── Name extraction ────────────────────────────────────────────────

MILITARY_RANK_RE = (
    r"(?:General\s+en\s+Jefe|Almirante\s+en\s+Jefe|Mayor\s+General|Vicealmirante|"
    r"General\s+de\s+Divisi[oó]n|Contralmirante|General\s+de\s+Brigada|"
    r"Capit[aá]n\s+de\s+Nav[ií]o|Teniente\s+Coronel|Coronel|"
    r"Capit[aá]n\s+de\s+Fragata|Capit[aá]n\s+de\s+Corbeta)"
)

# Spanish compound name particles that should NOT break name extraction
# "del Carmen", "del Valle", "del Mar", "de la Rosa", "de Los Ángeles", "de Jes[uú]s", etc.
NAME_PARTICLES = (
    r"del\s+Carmen|del\s+Valle|del\s+Mar|del\s+Pilar|del\s+Rosario|"
    r"de\s+la\s+Rosa|de\s+la\s+Cruz|de\s+Los\s+[ÁA]ngeles|de\s+Jes[uú]s|"
    r"de\s+las\s+Mercedes|de\s+los\s+Santos|de\s+[A-Z][a-záéíóúñ]+|del\s+[A-Z][a-záéíóúñ]+"
)

# Full character class for Spanish names (includes apostrophe/accent for D'Onofrio etc.)
NAME_CHAR = r"[A-ZÁÉÍÓÚÑÜa-záéíóúñü'´`\u2019\u2018]"
NAME_WORD = r"[A-ZÁÉÍÓÚÑÜa-záéíóúñü][A-ZÁÉÍÓÚÑÜa-záéíóúñü'´`\u2019\u2018]*"
# A name is: one or more name words, optionally with particles
NAME_RE = rf"(?:{NAME_WORD}(?:\s+(?:(?:{NAME_PARTICLES})|{NAME_WORD}))*)"


def extract_person_name_from_sumario(text):
    """Extract person name from SUMARIO-style text, handling military ranks and compound names."""

    # Strategy 1: "al ciudadano/a [RANK] Name Name, como/titular"
    pat1 = (
        rf"(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"(?:({MILITARY_RANK_RE})\s+)?"
        rf"({NAME_RE})"
        rf"(?:\s*,\s*(?:como|titular|Comandante|Director|quien))"
    )
    m = re.search(pat1, text)
    if m:
        rank = (m.group(1) or "").strip()
        name = m.group(2).strip()
        # Clean trailing institutional words that leaked in
        name = re.sub(r"\s+(?:como|titular|en\s+(?:su|la|el)|adscrit|del\s+Ministerio|para\s+(?:el|la)|que\s+en).*$", "", name, flags=re.IGNORECASE)
        if len(name) > 3 and name not in ["General", "Coronel", "Mayor", "Teniente"]:
            return rank, name

    # Strategy 1b: "traslada al ciudadano X como" (no comma before como)
    pat1b = (
        rf"(?:traslada|nombra|designa)\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"(?:({MILITARY_RANK_RE})\s+)?"
        rf"({NAME_RE})"
        rf"\s+como\s+"
    )
    m = re.search(pat1b, text)
    if m:
        rank = (m.group(1) or "").strip()
        name = m.group(2).strip()
        if len(name) > 3 and name not in ["General", "Coronel", "Mayor", "Teniente"]:
            return rank, name

    # Strategy 2: "designa como Fiscal... al ciudadano/a Name"
    pat2 = (
        rf"designa\s+como\s+.{{5,80}}?\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"({NAME_RE})"
        rf"(?:\s*,|\s*en\s+la)"
    )
    m = re.search(pat2, text)
    if m:
        name = m.group(1).strip()
        name = re.sub(r"\s+(?:como|titular|en\s+(?:su|la|el)|adscrit).*$", "", name, flags=re.IGNORECASE)
        if len(name) > 3:
            return "", name

    # Strategy 3: "al Diputado/a Name,"
    pat3 = rf"(?:al\s+Diputado|a\s+la\s+Diputada)\s+({NAME_RE})(?:\s*,)"
    m = re.search(pat3, text)
    if m:
        return "", m.group(1).strip()

    # Strategy 4: "el/la ciudadano/a Name, como"
    pat4 = rf"(?:la\s+ciudadana|el\s+ciudadano)\s+({NAME_RE})(?:\s*,\s*como)"
    m = re.search(pat4, text)
    if m:
        name = m.group(1).strip()
        if len(name) > 3:
            return "", name

    # Strategy 5: "se designa al ciudadano Name, en la Fiscalía..."
    pat5 = (
        rf"designa\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"({NAME_RE})"
        rf"(?:\s*,\s*(?:en\s+la|como|a\s+la))"
    )
    m = re.search(pat5, text)
    if m:
        name = m.group(1).strip()
        if len(name) > 3:
            return "", name

    # Strategy 6: "delega al/en el ciudadano [RANK] Name, en su carácter de..."
    pat6 = (
        rf"(?:delega\s+(?:al|en\s+el)\s+ciudadano|delega\s+(?:a\s+la|en\s+la)\s+ciudadana)\s+"
        rf"(?:({MILITARY_RANK_RE})\s+)?"
        rf"({NAME_RE})"
        rf"(?:\s*,\s*en\s+su\s+car[aá]cter)"
    )
    m = re.search(pat6, text)
    if m:
        rank = (m.group(1) or "").strip()
        name = m.group(2).strip()
        if len(name) > 3 and name not in ["General", "Coronel", "Mayor", "Teniente"]:
            return rank, name

    # Strategy 7: "designa al ciudadano [RANK] Name, en su carácter de..."
    pat7 = (
        rf"designa\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"(?:({MILITARY_RANK_RE})\s+)?"
        rf"({NAME_RE})"
        rf"(?:\s*,\s*en\s+su\s+car[aá]cter)"
    )
    m = re.search(pat7, text)
    if m:
        rank = (m.group(1) or "").strip()
        name = m.group(2).strip()
        if len(name) > 3 and name not in ["General", "Coronel", "Mayor", "Teniente"]:
            return rank, name

    # Strategy 8: "delega en la ciudadana/el ciudadano [RANK] Name, ..."
    pat8 = (
        rf"delega\s+en\s+(?:la\s+ciudadana|el\s+ciudadano)\s+"
        rf"(?:({MILITARY_RANK_RE})\s+)?"
        rf"({NAME_RE})"
        rf"(?:\s*,)"
    )
    m = re.search(pat8, text)
    if m:
        rank = (m.group(1) or "").strip()
        name = m.group(2).strip()
        if len(name) > 3 and name not in ["General", "Coronel", "Mayor", "Teniente"]:
            return rank, name

    # Strategy 9: "se confiere al ciudadano Name, la ORDEN..." or "se confiere al ciudadano Name la ORDEN..."
    pat9 = (
        rf"(?:se\s+confiere|se\s+impone)\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"({NAME_RE})"
        rf"(?:\s*,|\s+la\s+)"
    )
    m = re.search(pat9, text)
    if m:
        name = m.group(1).strip()
        if len(name) > 3:
            return "", name

    # Strategy 10 (fallback): "al ciudadano/a la ciudadana Name" followed by punctuation or end
    # Catches jubilaciones, pensiones, and other entries with a single named person
    pat10 = (
        rf"(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        rf"({NAME_RE})"
        rf"(?:\s*[.,;]|\s*$)"
    )
    m = re.search(pat10, text)
    if m:
        name = m.group(1).strip()
        # Exclude false matches like "la ciudadana y ciudadanos que en..."
        if len(name) > 3 and name.lower() not in ["y", "que"] and not name.lower().startswith("y "):
            return "", name

    return "", ""


def extract_person_name_from_body(text):
    """Extract FULL NAME (uppercase) from decree body text."""
    patterns = [
        r"Nombro\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]+?)\s*,\s*titular",
        r"se\s+designa\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+(" + NAME_RE + r")\s*,\s*como",
        r"se\s+confiere\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+(" + NAME_RE + r")\s+la\s+",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def extract_post_from_text(text):
    """Extract the position/post."""
    patterns = [
        r"como\s+(.+?)(?:\s*,\s*(?:en\s+calidad|del\s+Ministerio|adscrit|ente\s+adscrit|con\s+las\s+competencias|quien\s+ser))",
        r"como\s+(.+?)(?:\s*,\s*(?:del|de la|adscrit))",
        r"como\s+(.+?)(?:\s*[.])",
        # Fallback: "como X" at end of text (for split sub-entries)
        r"como\s+(.+?)$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            post = m.group(1).strip()
            # Clean trailing noise
            post = post.rstrip(",;. ")
            if len(post) > 300:
                post = post[:300] + "..."
            if len(post) > 2:
                return post
    return ""


def extract_subject_description(text, change_type):
    """Extract a subject/description for non-person entries (programs, decorations, etc.)."""
    t = text

    if change_type == "AUTORIZACION_UNIVERSITARIA":
        # Extract the university/institute name
        m = re.search(r"(?:al|a\s+la|a\s+las)\s+((?:Instituto|Universidad|Instituciones)[^,;.]{5,}?)(?:\s*,|\s+el\s+funcionamiento|\s+las?\s+carreras|\s+la\s+creaci)", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"se\s+ampl[ií]a\s+la\s+carrera\s+de\s+(.+?)(?:\s+al\s+Instituto)", t, re.IGNORECASE)
        if m:
            return "Ampliación: " + m.group(1).strip()

    if change_type == "PROGRAMA_EDUCATIVO":
        m = re.search(r"(Programa\s+Nacional\s+de\s+Formaci[oó]n[^,.;]{3,}?)(?:\s*[.,;]|\s+con\s+las)", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    if change_type == "CONDECORACION":
        m = re.search(r"((?:Medalla|Orden)[^,;]{5,}?)(?:\s*,|\s+en\s+su)", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"(ORDEN\s+FRANCISCO\s+DE\s+MIRANDA[^,;]*)", t)
        if m:
            return m.group(1).strip()

    if change_type in ("CREACION_MINISTERIO", "SUPRESION_MINISTERIO"):
        m = re.search(r"(?:se\s+crea|supresi[oó]n\s+del)\s+(Ministerio\s+del\s+Poder\s+Popular[^,.;]+)", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"se\s+crean\s+los\s+Despachos\s+del\s+Viceministro[^,.;]+", t, re.IGNORECASE)
        if m:
            return m.group(0).strip()

    if change_type == "REESTRUCTURACION":
        m = re.search(r"Restructuraci[oó]n\s+del\s+([^,.;]+)", t, re.IGNORECASE)
        if m:
            return "Reestructuración del " + m.group(1).strip()

    if change_type == "FUSION_UNIDADES":
        m = re.search(r"Fusi[oó]n[^,.;]{5,}?(?:\.\s|$)", t, re.IGNORECASE)
        if m:
            return m.group(0).strip().rstrip(".")

    if change_type == "REORGANIZACION_INSTITUCIONAL":
        m = re.search(r"reorganizaci[oó]n\s+del?\s+funcionamiento\s+del\s+([^,.;]+)", t, re.IGNORECASE)
        if m:
            return "Reorganización del " + m.group(1).strip()

    if change_type == "REFORMA_LEGISLATIVA":
        m = re.search(r"(LEY\s+DE\s+REFORMA[^.;]{5,}?)(?:\s+Art[ií]culo|\s*$)", t)
        if m:
            return m.group(1).strip()

    if change_type == "DELEGACION_FUNCIONES":
        m = re.search(r"se\s+(?:delega|ampl[ií]a\s+la\s+delegaci[oó]n)\s+(?:en\s+la\s+ciudadana|en\s+el\s+ciudadano|de\s+las\s+atribuciones)[^.;]+", t, re.IGNORECASE)
        if m:
            return m.group(0).strip()

    # Collective designations: "que en él/ella se mencionan, para ocupar los cargos..."
    if change_type in ("DESIGNACION_OTRO", "DESIGNACION_VICEMINISTRO", "DESIGNACION_DIRECTOR"):
        # Try to get what kind of posts: "como Viceministras y Viceministros, del Ministerio..."
        m = re.search(r"como\s+(.+?)(?:\s*,\s*(?:del\s+Ministerio|adscrit|en\s+condici))", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # "para ocupar los cargos que en él se indican, del Ministerio..."
        m = re.search(r"para\s+ocupar\s+los\s+cargos\s+que\s+en\s+[eé]l\s+se\s+indican\s*,\s*del\s+(Ministerio[^.;]+)", t, re.IGNORECASE)
        if m:
            return "Varios cargos del " + m.group(1).strip()

    # Juntas: extract entity name
    if change_type == "DESIGNACION_JUNTA":
        # Try to get "Junta X de la empresa «NAME»"
        m = re.search(r"(Junta\s+(?:Administradora|Interventora|Directiva)\s+(?:Especial\s+)?(?:(?:Ad-Hoc\s+)?(?:de\s+la\s+(?:entidad\s+de\s+trabajo|empresa)\s+)?)?[\"«]?(?:[A-ZÁÉÍÓÚÑÜ][^\"»,.;]{3,})[\"»]?)", t, re.IGNORECASE)
        if m:
            result = m.group(1).strip()
            # Clean "de de"
            result = re.sub(r"\bde\s+de\b", "de", result)
            return result
        m = re.search(r"(Junta\s+(?:Administradora|Interventora|Directiva)[^.;]+)", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Comisiones
    if change_type in ("COMISION_CONTRATACIONES", "COMITE_LICITACIONES"):
        m = re.search(r"(Comisi[oó]n\s+de\s+Contrataciones[^.;]*?)(?:\s*(?:;|estar[aá]|la\s+cual))", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"(Comit[eé]\s+de\s+Licitaciones[^.;]*?)(?:\s*(?:;|estar[aá]|la\s+cual))", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Condecoraciones colectivas
    if change_type == "CONDECORACION":
        m = re.search(r"((?:condecoraci[oó]n|Orden|Medalla)\s+[^,;]+?)(?:\s*,\s*(?:en\s+su|a\s+las?))", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Inspectores/Comisionados colectivos
    if change_type in ("DESIGNACION_INSPECTOR", "DESIGNACION_COMISIONADO"):
        m = re.search(r"como\s+(.+?)(?:\s+(?:por\s+el\s+t[eé]rmino|a\s+nivel|que\s+en))", t, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return ""


def extract_institution(text):
    """Extract the specific sub-institution from entry text.
    Only returns sub-institutions (Fundación, Instituto, Corporación, etc.),
    NOT the parent ministry — that's in the 'organism' column."""
    patterns = [
        # Specific sub-institution: "adscrita al Instituto/Fundación/Corporación..."
        r"adscrit[oa]?\s+(?:al?|a\s+la)\s+((?:Instituto|Fundaci[oó]n|Corporaci[oó]n|Servicio\s+(?:Aut[oó]nomo|Desconcentrado|Coordinado)|Empresa\s+del\s+Estado|Sociedad\s+Mercantil|Fondo\s+Nacional|Complejo\s+Industrial)[^,.;]{5,})",
        # "del/de la Fundación/Instituto..."
        r"(?:del|de\s+la)\s+((?:Fundaci[oó]n|Instituto|Corporaci[oó]n|Servicio\s+(?:Aut[oó]nomo|Desconcentrado|Coordinado))[^,.;]{5,})",
        # Hospital/Clínica/Dirección Estadal
        r"adscrit[oa]?\s+(?:al?|a\s+la)\s+((?:Hospital|Cl[ií]nica|Direcci[oó]n\s+(?:Estadal|de\s+Salud)|Centro\s+Nacional|Corporaci[oó]n\s+de\s+Salud)[^,.;]{5,})",
        # Specific known entities by acronym
        r"(?:del|de\s+la|al?)\s+((?:SENIAT|INATUR|INPSASEL|INAC|INAPYMI|FONACIT|CONVIASA|CORPOELEC|CUSPAL|VENETUR|VENTEL|VENVIDRIO|FONDOIN|COVEPLAST|CORSOVENCA|IAIM|SEDEFANB|CEOFANB|DGCIM|INSAMONAGAS|CORPOSALUD|FUNDASALUD)[^,.;]*)",
        # "de la empresa «NAME»"
        r"(?:de\s+la\s+empresa|la\s+empresa)\s+[\"«]?([A-ZÁÉÍÓÚÑÜ][^,.;\"»]{3,})[\"»]?",
        # Fiscalía
        r"(?:en\s+la|a\s+la)\s+(Fiscal[ií]a\s+[^,.;]{5,})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            inst = m.group(1).strip()
            # Clean trailing noise
            inst = re.sub(r"\s*(?:;|y\s+se\s+|estar[aá]\s+|la\s+cual\s+|quien\s+|para\s+el\s+Ejercicio).*$", "", inst)
            if len(inst) > 200:
                inst = inst[:200]
            return inst
    return ""


def extract_organism(entry_text, section_header, post_text=""):
    """Extract the organism/institution the post is tied to.

    Uses three sources:
    1. The SUMARIO section header (e.g., "MINISTERIO DEL PODER POPULAR PARA LA SALUD")
    2. Specific sub-institution mentioned in the entry (e.g., "INSAMONAGAS", "SENIAT")
    3. Contextual inference from the post itself
    """
    combined = entry_text + " " + post_text

    # First try to get the specific sub-institution from the entry text
    specific_patterns = [
        # "adscrita al/a la [Entity]..."
        r"adscrit[oa]?\s+(?:al?|a\s+la)\s+((?:Instituto|Fundaci[oó]n|Corporaci[oó]n|Servicio\s+(?:Aut[oó]nomo|Desconcentrado|Coordinado)|Empresa\s+del\s+Estado|Sociedad\s+Mercantil|Fondo\s+Nacional|Complejo\s+Industrial|C\.A\.|S\.A\.)[^,.;]{3,})",
        # Entities with parenthetical acronyms: "SENIAT", "(INATUR)", "(CONVIASA)", etc.
        r"(?:del|de\s+la|de\s+los|al?)\s+((?:SENIAT|INATUR|INPSASEL|INAC|INAPYMI|FONACIT|CONVIASA|CORPOELEC|CUSPAL|VENETUR|VENTEL|VENVIDRIO|FONDOIN|COVEPLAST|CORSOVENCA|IAIM|SEDEFANB|CEOFANB)[^,.;]*)",
        # Dirección Estadal / Hospital / ASIC
        r"(?:adscrit[oa]?\s+(?:al?|a\s+la)\s+)(Direcci[oó]n\s+(?:Estadal|de\s+Salud)[^,.;]+)",
        r"(?:adscrit[oa]?\s+(?:al?|a\s+la)\s+)((?:Hospital|Cl[ií]nica|Centro\s+Nacional)[^,.;]+)",
        r"(?:adscrit[oa]?\s+(?:al?|a\s+la)\s+)(Corporaci[oó]n\s+de\s+Salud[^,.;]+)",
        # "de la empresa XXXX"
        r"(?:de\s+la\s+empresa|la\s+empresa)\s+[\"«]?([A-ZÁÉÍÓÚÑÜ][^,.;\"»]{3,})[\"»]?",
        # Fiscalía specific
        r"(?:en\s+la|a\s+la)\s+(Fiscal[ií]a\s+[^,.;]{5,})",
        # Sala de Flagrancia / Unidad de Depuración
        r"(?:en\s+la|a\s+la)\s+((?:Sala\s+de\s+Flagrancia|Unidad\s+de\s+Depuraci[oó]n)[^,.;]*)",
        # Zona Educativa
        r"(Zona\s+Educativa\s+del\s+estado\s+[A-ZÁÉÍÓÚÑÜa-záéíóúñü]+)",
    ]

    specific_inst = ""
    for pat in specific_patterns:
        m = re.search(pat, combined, re.IGNORECASE)
        if m:
            specific_inst = m.group(1).strip()
            # Clean trailing noise
            specific_inst = re.sub(r"\s*(?:;|y\s+se\s+|estar[aá]\s+|la\s+cual\s+|quien\s+|para\s+el\s+).*$", "", specific_inst)
            if len(specific_inst) > 200:
                specific_inst = specific_inst[:200]
            break

    # Use section header as the parent organism
    parent_org = section_header.strip() if section_header else ""
    # Clean section header: remove any leaked entry text
    parent_org = re.sub(r"\s+", " ", parent_org).strip()
    # Truncate at entry starters that leaked into the header
    for kw in ["Resoluci", "Decreto ", "Providencia ", "Acuerdo ", "Aviso "]:
        idx = parent_org.find(kw)
        if idx > 10:
            parent_org = parent_org[:idx].strip()
            break
    # Also truncate at common sub-headers that leaked
    parent_org = re.split(r"\s+(?:Planta\s+de\s+Autobuses)", parent_org, maxsplit=1)[0].strip()

    # If no section header, try to get the ministry from the entry text
    if not parent_org:
        m = re.search(r"(?:del|de\s+la)\s+(Ministerio\s+del\s+Poder\s+Popular[^,.;]+)", combined, re.IGNORECASE)
        if m:
            parent_org = m.group(1).strip()
        else:
            m = re.search(r"(Ministerio\s+del\s+Poder\s+Popular[^,.;]+)", combined, re.IGNORECASE)
            if m:
                parent_org = m.group(1).strip()
        # Clean leaked entry text from regex-extracted parent org
        if parent_org:
            for kw in ["Resoluci", "Decreto ", "Providencia ", "Acuerdo ", "Aviso "]:
                idx = parent_org.find(kw)
                if idx > 10:
                    parent_org = parent_org[:idx].strip()
                    break

    # For fiscales without explicit header, the parent is always Ministerio Público
    if not parent_org and ("fiscal" in combined.lower() and ("fiscal[ií]a" in combined.lower() or "ministerio p" in combined.lower())):
        parent_org = "Ministerio Público"

    # For CICPC / police investigation entries
    if not parent_org and any(kw in combined.lower() for kw in ["investigaci", "delincuencia organizada", "criminal", "cicpc"]):
        parent_org = "Ministerio del Poder Popular para Relaciones Interiores, Justicia y Paz"

    # For Centro Internacional de Inversión Productiva
    if not parent_org and "centro internacional de inversi" in combined.lower():
        parent_org = "Centro Internacional de Inversión Productiva"

    # For INPSASEL
    if not parent_org and "inpsasel" in combined.lower():
        parent_org = "INPSASEL"

    # For presidential decrees
    if not parent_org and ("presidencia de la rep" in combined.lower() or "decreto" in combined.lower()):
        m = re.search(r"(?:adscrit[oa]?\s+al?\s+|del\s+)(Ministerio\s+del\s+Poder\s+Popular[^,.;]+)", combined, re.IGNORECASE)
        if m:
            parent_org = m.group(1).strip()
        elif "presidencia" in combined.lower():
            parent_org = "Presidencia de la República"

    # Build the organism string
    if specific_inst and parent_org:
        # Don't duplicate if the specific institution is the same as the parent
        if specific_inst.lower() not in parent_org.lower() and parent_org.lower() not in specific_inst.lower():
            return f"{specific_inst} ({parent_org})"
        return specific_inst if len(specific_inst) > len(parent_org) else parent_org
    elif specific_inst:
        return specific_inst
    elif parent_org:
        return parent_org

    return ""


def clean_trailing_headers(text):
    """Remove trailing ALL-CAPS section headers that leaked from the next SUMARIO section."""
    # These patterns match section headers that appear at the end of entry text
    trailing_headers = [
        r"\s+MINISTERIO\s+DEL\s+PODER\s+POPULAR[\sA-ZÁÉÍÓÚÑÜ,()]*$",
        r"\s+MINISTERIO\s+P[ÚU]BLICO\s*$",
        r"\s+PRESIDENCIA\s+DE\s+LA\s+REP[ÚU]BLICA\s*$",
        r"\s+ASAMBLEA\s+NACIONAL\s*$",
        r"\s+TRIBUNAL\s+SUPREMO[\sA-ZÁÉÍÓÚÑÜ]*$",
        r"\s+CONTRALOR[ÍI]A\s+GENERAL[\sA-ZÁÉÍÓÚÑÜ]*$",
        r"\s+CONSEJO\s+NACIONAL[\sA-ZÁÉÍÓÚÑÜ]*$",
        r"\s+BANCO\s+CENTRAL\s+DE\s+VENEZUELA\s*$",
        r"\s+VICEPRESIDENCIA\s+(?:EJECUTIVA|SECTORIAL)[\sA-ZÁÉÍÓÚÑÜ,]*$",
        r"\s+SENIAT\s*$",
        r"\s+INPSASEL\s*$",
        r"\s+FONACIT\s*$",
        r"\s+INAC\s*$",
        r"\s+CUSPAL\s*$",
        r"\s+Superintendencia[\s\w]*$",
    ]
    for pat in trailing_headers:
        text = re.sub(pat, "", text)
    return text.strip()


def extract_decree_number(text):
    """Extract decree number if present."""
    m = re.search(r"Decreto\s+N[°º.]\s*(\d[\d.]+)", text)
    if m:
        return m.group(1).rstrip(".")
    return ""


# ─── SUMARIO parsing ────────────────────────────────────────────────

def parse_sumario_entries(text):
    """Split SUMARIO into individual entries with their section headers.
    Returns list of (entry_text, section_header) tuples."""
    sumario_start = text.find("SUMARIO")
    if sumario_start < 0:
        return []

    sumario_text = text[sumario_start + 7:]  # skip "SUMARIO"

    # Find end of SUMARIO
    end_markers = [
        r"\d{3}[.,]\d{3}\s+GACETA\s+OFICIAL",
        r"\d+\s+GACETA\s+OFICIAL\s+DE\s+LA\s+REP",
    ]
    end_pos = len(sumario_text)
    for marker in end_markers:
        m = re.search(marker, sumario_text)
        if m:
            end_pos = min(end_pos, m.start())
            break

    m2 = re.search(r"\nDECRETA\b|\nArt[ií]culo\s+\d", sumario_text[:end_pos])
    if m2:
        end_pos = min(end_pos, m2.start())

    pres_matches = list(re.finditer(r"PRESIDENCIA\s+DE\s+LA\s+REP", sumario_text[:end_pos]))
    if len(pres_matches) >= 2:
        end_pos = min(end_pos, pres_matches[1].start())

    sumario_raw = sumario_text[:end_pos]

    if len(sumario_raw.strip()) < 20:
        return []

    # Known section header patterns (these appear as uppercase blocks in the SUMARIO)
    section_header_re = (
        r"(?:PRESIDENCIA\s+DE\s+LA\s+REP[ÚU]BLICA|"
        r"VICEPRESIDENCIA\s+(?:EJECUTIVA|SECTORIAL)[^A-Z]*|"
        r"MINISTERIO\s+DEL\s+PODER\s+POPULAR[^A-Z]*(?:\n[^A-Z\n]*)*|"
        r"MINISTERIO\s+P[ÚU]BLICO|"
        r"ASAMBLEA\s+NACIONAL|"
        r"TRIBUNAL\s+SUPREMO\s+DE\s+JUSTICIA[^A-Z]*|"
        r"CONTRALOR[ÍI]A\s+GENERAL[^A-Z]*|"
        r"CONSEJO\s+(?:NACIONAL\s+(?:ELECTORAL|DE\s+UNIVERSIDADES)|FEDERAL\s+DE\s+GOBIERNO)[^A-Z]*|"
        r"BANCO\s+CENTRAL\s+DE\s+VENEZUELA|"
        r"ESTADO\s+[A-ZÁÉÍÓÚÑÜ]+\s*\n\s*ALCALD[ÍI]A[^A-Z]*|"
        r"SENIAT|INPSASEL|FONACIT|FUNDACITE[^A-Z]*|"
        r"SUPERINTENDENCIA\s+[^A-Z]*)"
    )

    # Process line by line to identify headers and entries
    lines = sumario_raw.split("\n")
    current_header = ""
    accumulated_text = ""
    entries = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this line is part of a section header (ALL CAPS, no entry starters)
        is_header = False
        upper_ratio = sum(1 for c in stripped if c.isupper()) / max(len(stripped.replace(" ", "")), 1)
        has_entry_start = bool(re.match(r"(?:Resoluci[oó]n|Decreto|Providencia|Acuerdo|Ley\s+de|Aviso)", stripped, re.IGNORECASE))

        if upper_ratio > 0.7 and not has_entry_start and len(stripped) > 5:
            # Check if it matches known header patterns
            test = collapse_ws(current_header + " " + stripped) if current_header else stripped
            if re.search(r"(?:MINISTERIO|PRESIDENCIA|VICEPRESIDENCIA|ASAMBLEA|TRIBUNAL|CONTRALOR|CONSEJO|BANCO\s+CENTRAL|SENIAT|INPSASEL|FONACIT|FUNDACITE|SUPERINTENDENCIA|ESTADO\s+[A-Z]|ALCALD)", test, re.IGNORECASE):
                is_header = True
            elif re.match(r"^(?:PARA\s+|DE\s+|DEL\s+|Y\s+)", stripped) and current_header:
                # Continuation of a multi-line header like "MINISTERIO DEL PODER POPULAR\nPARA LA SALUD"
                is_header = True

        if is_header:
            # This is a section header line
            if current_header and not current_header.endswith(" "):
                current_header += " "
            current_header_candidate = collapse_ws(current_header + stripped)
            # Only reset header if it's a new top-level header
            if re.match(r"(?:MINISTERIO|PRESIDENCIA|VICEPRESIDENCIA|ASAMBLEA|TRIBUNAL|CONTRALOR|CONSEJO|BANCO|ESTADO)", stripped):
                current_header = stripped
            else:
                current_header = current_header_candidate
        else:
            accumulated_text += " " + stripped

    # Now re-parse with headers using the collapsed text approach
    # We need a different strategy: process the raw text keeping track of headers

    # Reset and do a proper pass
    entries = []
    current_header = ""
    sumario_collapsed = collapse_ws(sumario_raw)

    # Split the raw sumario into segments by known section headers
    # First, identify all header positions in the collapsed text
    header_pattern = (
        r"((?:PRESIDENCIA\s+DE\s+LA\s+REP[ÚU]BLICA|"
        r"VICEPRESIDENCIA\s+(?:EJECUTIVA|SECTORIAL)\s+[A-ZÁÉÍÓÚÑÜ\s,]+|"
        r"MINISTERIO\s+DEL\s+PODER\s+POPULAR\s+[A-ZÁÉÍÓÚÑÜ\s,()]+|"
        r"MINISTERIO\s+P[ÚU]BLICO|"
        r"ASAMBLEA\s+NACIONAL|"
        r"TRIBUNAL\s+SUPREMO\s+DE\s+JUSTICIA[A-ZÁÉÍÓÚÑÜ\s]*|"
        r"CONTRALOR[ÍI]A\s+GENERAL\s+DE\s+LA\s+REP[ÚU]BLICA|"
        r"CONSEJO\s+(?:NACIONAL\s+(?:ELECTORAL|DE\s+UNIVERSIDADES)|FEDERAL\s+DE\s+GOBIERNO)(?:\s+[A-Za-záéíóúñüÁÉÍÓÚÑÜ]+)*|"
        r"BANCO\s+CENTRAL\s+DE\s+VENEZUELA|"
        r"ESTADO\s+[A-ZÁÉÍÓÚÑÜ]+\s+ALCALD[ÍI]A\s+[A-ZÁÉÍÓÚÑÜ\s]+)"
        r")\s*(?=(?:Resoluci[oó]n|Decreto|Providencia|Acuerdo|Ley\s+de|Aviso))"
    )

    # Find all headers that precede entries
    header_positions = []
    for m in re.finditer(header_pattern, sumario_collapsed, re.IGNORECASE):
        header_positions.append((m.start(), m.end(), m.group(1).strip()))

    # Also try to find sub-headers like "SENIAT", "FONACIT", "INPSASEL" etc.
    sub_header_pattern = (
        r"((?:SENIAT|INPSASEL|FONACIT|FUNDACITE\s+[A-ZÁÉÍÓÚÑÜ]+|INAC|CUSPAL|"
        r"Superintendencia\s+de\s+Bienes\s+P[úu]blicos|"
        r"Planta\s+de\s+Autobuses\s+[A-Za-záéíóúñü\s]+))"
        r"\s*(?=(?:Resoluci[oó]n|Decreto|Providencia|Acuerdo|Ley\s+de|Aviso))"
    )
    for m in re.finditer(sub_header_pattern, sumario_collapsed, re.IGNORECASE):
        header_positions.append((m.start(), m.end(), m.group(1).strip()))

    header_positions.sort(key=lambda x: x[0])

    # Now split entries and assign headers
    entry_starters = r"((?:Resoluci[oó]n|Decreto|Providencia|Acuerdo|Ley\s+de|Aviso\s+Oficial?)\s+(?:mediante|N[°º.]))"
    parts = re.split(entry_starters, sumario_collapsed, flags=re.IGNORECASE)

    # Build a position map: for each character position in sumario_collapsed,
    # determine which header applies
    # Simpler approach: for each entry, find the last header before it
    current_pos = 0
    current_hdr = ""
    entry_list = []

    i = 0
    pos = 0
    while i < len(parts):
        segment = parts[i]
        # Check if any header starts within this segment
        seg_start = sumario_collapsed.find(segment, pos)
        if seg_start >= 0:
            for hp_start, hp_end, hp_text in header_positions:
                if hp_start >= pos and hp_start <= seg_start + len(segment):
                    current_hdr = hp_text
            pos = seg_start + len(segment)

        if i > 0 and i % 2 == 1 and i + 1 < len(parts):
            entry = (parts[i] + parts[i + 1]).strip()
            if len(entry) > 10:
                # Apply filters
                if re.search(r"Decreto\s+N[°º.]\s*[\d.]+\s+\d{2}\s+de\s+\w+\s+de\s+\d{4}\s+[A-ZÁÉÍÓÚÑÜ]", entry):
                    pass
                elif re.search(r"^Resoluci[oó]n\s+N[°º.]\s*\d+\s+de\s+fecha\s+\d+\s+de\s+\w+\s+de\s+20\d\d", entry):
                    pass
                elif re.search(r"^Decreto\s+N[°º.]\s*[\d.]+\s*(?:,\s*)?de\s+fecha\s+\d+\s+de\s+\w+\s+de\s+(?:19|20)\d\d", entry):
                    pass
                else:
                    entry_list.append((clean_trailing_headers(entry), current_hdr))
        i += 1

    return entry_list


# ─── Body parsing for decrees ───────────────────────────────────────

def parse_body_decrees(text):
    """Parse decree body text for detailed person/post info.
    Returns list of dicts with name, post, decree_number, context."""
    results = []
    norm_text = collapse_ws(text)

    # Find all "Artículo N°. Nombro al ciudadano..." blocks
    nombro_pattern = (
        r"Art[ií]culo\s+(\d+)[°º]?\.\s*"
        r"Nombro\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]+?)"
        r"\s*,\s*titular\s+de\s+la\s+c[eé]dula\s+de\s+identidad\s+N[°º]?\s*V-\s*[\d.]+\s*,"
        r"\s*como\s+(.+?)(?:\s*,\s*(?:con\s+las\s+competencias|del\s+Ministerio|en\s+condici[oó]n|quien\s+ser|ente\s+adscrit))"
    )

    for m in re.finditer(nombro_pattern, norm_text, re.IGNORECASE):
        name = m.group(2).strip()
        post = m.group(3).strip()
        # Find decree number before this article
        pre_text = norm_text[max(0, m.start() - 1500):m.start()]
        decree = ""
        # Find the LAST (closest) decree number before this article
        decree_matches = list(re.finditer(r"Decreto\s+N[°º.]\s*(\d[\d.]+)", pre_text))
        if decree_matches:
            decree = decree_matches[-1].group(1).rstrip(".")
        context = norm_text[m.start():m.end() + 200]

        results.append({
            "name": name,
            "post": post,
            "decree_number": decree,
            "context": context,
            "is_military_person": is_military_person(name + " " + context),
            "military_rank": extract_military_rank(context),
            "is_military_post": is_military_post(post + " " + context),
        })

    # Also find "se designa al ciudadano..." in resolution bodies
    designa_pattern = (
        r"se\s+designa\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        r"((?:General\s+de\s+Divisi[oó]n|General\s+de\s+Brigada|Mayor\s+General|"
        r"Coronel|Teniente\s+Coronel|Capit[aá]n)?\s*"
        r"[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜa-záéíóúñü\s]+?)"
        r"\s*,\s*como\s+(.+?)(?:\s*(?:,\s*adscrit|,\s*del\s+Ministerio|,\s*en\s+calidad|,\s*ente\s+adscrit|\.\s))"
    )

    for m in re.finditer(designa_pattern, norm_text, re.IGNORECASE):
        name = m.group(1).strip()
        post = m.group(2).strip()
        context = norm_text[m.start():m.end() + 200]
        results.append({
            "name": name,
            "post": post,
            "decree_number": "",
            "context": context,
            "is_military_person": is_military_person(name),
            "military_rank": extract_military_rank(name),
            "is_military_post": is_military_post(post + " " + context),
        })

    # Find "se confiere" for decorations
    confiere_pattern = (
        r"se\s+confiere\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)?\s*"
        r"(?:la\s+)?[\"«]?ORDEN\s+FRANCISCO\s+DE\s+MIRANDA[\"»]?"
    )
    for m in re.finditer(confiere_pattern, norm_text, re.IGNORECASE):
        # Look for the name after
        post_text = norm_text[m.start():m.end() + 500]
        nm = re.search(r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]+?)\s+C\.I\.", post_text)
        if nm:
            results.append({
                "name": nm.group(1).strip(),
                "post": "Orden Francisco de Miranda",
                "decree_number": "",
                "context": post_text[:300],
                "is_military_person": False,
                "military_rank": "",
                "is_military_post": False,
            })

    return results


# ─── Institutional reorganization expansion ─────────────────────────

def expand_reorganizacion(pdf_path, gazette_num, gazette_type, date, original_record):
    """Expand a REORGANIZACION_INSTITUCIONAL record into individual rows
    by parsing the decree body for suppressions, transfers, and adscription changes."""
    text = extract_text(pdf_path)
    norm = re.sub(r"\s+", " ", text)
    records = []

    base = {
        "gazette_number": gazette_num,
        "gazette_type": gazette_type,
        "gazette_date": date,
        "decree_number": original_record.get("decree_number", ""),
        "is_military_person": "NO",
        "military_rank": "",
        "is_military_post": "NO",
    }
    parent_org = "Ministerio del Poder Popular del Despacho de la Presidencia y Seguimiento de la Gestión de Gobierno"

    # ── Art 2: Transfer of Misión to another Ministry ──
    m = re.search(
        r"Se\s+transfiere[^.]+?(Misi[oó]n\s+[^,]+?),?\s+creada\s+mediante.+?al\s+(Ministerio[^.]+?)\.\s+Las",
        norm, re.IGNORECASE
    )
    if m:
        records.append({**base,
            "change_type": "TRANSFERENCIA_COMPETENCIAS",
            "person_name": "",
            "post_or_position": f"Transferencia de {m.group(1).strip()} al {m.group(2).strip()}",
            "institution": m.group(1).strip(),
            "organism": m.group(2).strip(),
            "summary": f"Art 2: Se transfiere {m.group(1).strip()} al {m.group(2).strip()}",
        })

    # ── Art 3: Suppressions ──
    for item_m in re.finditer(
        r"(\d)\.\s+(?:La\s+|El\s+)((?:Fundaci[oó]n|Centro)\s+[^,]+?)(?:,\s*creada?)",
        norm, re.IGNORECASE
    ):
        entity = item_m.group(2).strip()
        records.append({**base,
            "change_type": "SUPRESION_ENTE",
            "person_name": "",
            "post_or_position": f"Supresión y liquidación",
            "institution": entity,
            "organism": parent_org,
            "summary": f"Art 3.{item_m.group(1)}: Supresión de {entity}",
        })

    # ── Art 9: Absorption (Fundación José Félix Ribas → Fundación Misión Negra Hipólita) ──
    m = re.search(
        r"Fundaci[oó]n\s+Jos[eé]\s+F[eé]lix\s+Ribas\s+ser[aá]n\s+continuadas\s+por\s+la\s+(Fundaci[oó]n\s+[^,]+?),?\s+adscrita\s+al\s+(Ministerio[^.]+?)\.",
        norm, re.IGNORECASE
    )
    if m:
        records.append({**base,
            "change_type": "TRANSFERENCIA_COMPETENCIAS",
            "person_name": "",
            "post_or_position": "Absorción de Fundación José Félix Ribas (FUNDARIBAS)",
            "institution": m.group(1).strip(),
            "organism": parent_org,
            "summary": f"Art 9: Fundación José Félix Ribas absorbida por {m.group(1).strip()}",
        })

    # ── Art 14: Adscription changes ──
    for item_m in re.finditer(
        r"Se\s+adscribe\s+al\s+(Ministerio[^.]{10,80}?)\s+"
        r"(?:el\s+Servicio\s+Desconcentrado\s+denominado\s+|la\s+Fundaci[oó]n\s+|el\s+Consejo\s+Nacional\s+)"
        r"([^,]+)",
        norm, re.IGNORECASE
    ):
        dest_ministry = item_m.group(1).strip()
        entity = item_m.group(2).strip()
        # Prefix back the entity type
        pre_text = norm[item_m.start():item_m.end()]
        if "Servicio Desconcentrado" in pre_text:
            entity_full = "Servicio Desconcentrado " + entity
        elif "Fundaci" in pre_text:
            entity_full = "Fundación " + entity
        elif "Consejo Nacional" in pre_text:
            entity_full = "Consejo Nacional " + entity
        else:
            entity_full = entity

        records.append({**base,
            "change_type": "CAMBIO_ADSCRIPCION",
            "person_name": "",
            "post_or_position": f"Cambio de adscripción al {dest_ministry}",
            "institution": entity_full,
            "organism": dest_ministry,
            "summary": f"Art 14: {entity_full} adscrita al {dest_ministry}",
        })

    return records


# ─── Multi-person entry splitting ────────────────────────────────────

def split_multi_person_entry(entry_text, section_header):
    """Split a SUMARIO entry that contains multiple designations into individual entries.
    Returns list of (sub_entry_text, section_header) tuples.
    If the entry is a single-person entry, returns the original as-is."""

    results = []

    # Strategy 0: "a los ciudadanos X y Y, respectivamente" — always check this first
    resp_pattern = rf"a\s+los\s+ciudadanos\s+({NAME_RE})\s+y\s+({NAME_RE})\s*,\s*respectivamente\s*,\s*como\s+(.+?)(?:\.\s|$)"
    m = re.search(resp_pattern, entry_text, re.IGNORECASE)
    if m:
        name1 = m.group(1).strip()
        name2 = m.group(2).strip()
        posts = m.group(3).strip()
        post_match = re.match(r"(.+?)\s+(?:Principal|Titular)\s+y\s+(.+?)(?:\s+del|\s+de la|\s+ante|\s*$)", posts, re.IGNORECASE)
        if post_match:
            post1 = post_match.group(1).strip() + " Principal"
            post2 = post_match.group(1).strip() + " Suplente"
        else:
            post1 = posts
            post2 = posts
        results.append((f"se designa al ciudadano {name1}, como {post1}", section_header))
        results.append((f"se designa al ciudadano {name2}, como {post2}", section_header))
        return results

    # Pattern: multiple "como X" clauses separated by ";" or "y se nombra/elige"
    # Detect multi-person entries
    como_count = len(re.findall(r"\bcomo\b", entry_text, re.IGNORECASE))
    if como_count < 2:
        return [(entry_text, section_header)]

    # Strategy 1: AN election pattern
    # "se elige al Diputado X, como Y; al Diputado Z, como W, y la Diputada A, como B; se elige a la ciudadana C, como D"
    # Match each person-post pair: [title] Name, como Post
    an_pattern = (
        rf"(?:se\s+elige\s+)?(?:y\s+)?(?:al\s+(?:Diputado|ciudadano)|a\s+la\s+(?:Diputada|ciudadana)|la\s+Diputada|el\s+Diputado)\s+"
        rf"({NAME_RE})"
        rf"\s*,\s*como\s+((?:President[ea]|Primer[oa]?\s+Vicepresidenta?|Segund[oa]\s+Vicepresidenta?|Secretari[oa]|Subsecretari[oa]|Vicepresidenta?)[^,;]*)"
    )
    an_matches = list(re.finditer(an_pattern, entry_text, re.IGNORECASE))
    if len(an_matches) >= 2:
        for m in an_matches:
            name = m.group(1).strip()
            post = m.group(2).strip()
            # Clean trailing noise from post
            post = re.sub(r"\s*(?:para\s+el\s+per[ií]odo|;\s*y?\s*$)", "", post).strip()
            post = post.rstrip(",;. ")
            sub_entry = f"se elige al ciudadano {name}, como {post}"
            results.append((sub_entry, section_header))
        if results:
            return results

    # Strategy 2: "se nombra al ciudadano X, como Y; y se nombra al ciudadano Z, como W"
    # Split on "; y se nombra" or "; se nombra"
    nombra_split = re.split(
        r"[;.]\s*(?:y\s+)?se\s+nombra\s+",
        entry_text, flags=re.IGNORECASE
    )
    if len(nombra_split) >= 2:
        # First chunk keeps the original prefix
        results.append((nombra_split[0].strip(), section_header))
        for chunk in nombra_split[1:]:
            sub = "se nombra " + chunk.strip()
            # Clean trailing period/noise
            sub = re.sub(r"\s*,?\s*(?:en\s+condici[oó]n\s+de\s+Encargad[oa]s?)\s*\.?\s*$", "", sub)
            results.append((sub, section_header))
        if len(results) >= 2:
            return results

    # Strategy 3: Multiple "Artículo N°. Nombro al ciudadano..." in body-parsed entries
    art_matches = list(re.finditer(
        r"Art[ií]culo\s+\d+[°º]?\.\s*Nombro\s+(?:al\s+ciudadano|a\s+la\s+ciudadana)\s+"
        r"([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s]+?)"
        r"\s*,\s*titular\s+de\s+la\s+c[eé]dula[^,]+,"
        r"\s*como\s+([^,]+)",
        entry_text, re.IGNORECASE
    ))
    if len(art_matches) >= 2:
        for m in art_matches:
            name = m.group(1).strip()
            post = m.group(2).strip()
            sub = f"Nombro al ciudadano {name}, como {post}"
            results.append((sub, section_header))
        return results

    # No split needed
    return [(entry_text, section_header)]


# ─── Main processing ────────────────────────────────────────────────

def process_gazette(pdf_path, gazette_num, gazette_type):
    """Process a single gazette and return list of change records."""
    text = extract_text(pdf_path)
    date = extract_date(text)

    records = []

    # Parse SUMARIO entries
    sumario_entries = parse_sumario_entries(text)

    # Parse body for detailed designations
    body_decrees = parse_body_decrees(text)

    # Build records from SUMARIO — split multi-person entries first
    expanded_entries = []
    for entry, section_header in sumario_entries:
        expanded_entries.extend(split_multi_person_entry(entry, section_header))

    for entry, section_header in expanded_entries:
        change_type = classify_change(entry)
        name_rank, person = extract_person_name_from_sumario(entry)
        post = extract_post_from_text(entry)
        if not post:
            post = extract_subject_description(entry, change_type)
        institution = extract_institution(entry)
        organism = extract_organism(entry, section_header, post)
        decree_num = extract_decree_number(entry)
        mil_person = is_military_person(entry)
        mil_post = is_military_post(entry + " " + institution + " " + organism)
        mil_rank = name_rank if name_rank else extract_military_rank(entry)

        records.append({
            "gazette_number": gazette_num,
            "gazette_type": gazette_type,
            "gazette_date": date,
            "decree_number": decree_num,
            "change_type": change_type,
            "person_name": person,
            "post_or_position": post,
            "institution": institution,
            "organism": organism,
            "is_military_person": "SI" if mil_person else "NO",
            "military_rank": mil_rank,
            "is_military_post": "SI" if mil_post else "NO",
            "summary": entry[:500],
        })

    # Expand REORGANIZACION_INSTITUCIONAL into individual change records
    expanded = []
    for r in records:
        if r["change_type"] == "REORGANIZACION_INSTITUCIONAL":
            sub_records = expand_reorganizacion(pdf_path, gazette_num, gazette_type, date, r)
            if sub_records:
                # Keep the original as a summary header, add the detailed rows
                expanded.append(r)
                expanded.extend(sub_records)
            else:
                expanded.append(r)
        else:
            expanded.append(r)
    records = expanded

    # Check if we have collective entries that need OCR
    has_collective = any(
        (not r["person_name"] or r["person_name"].startswith("y ") or "ciudadan" in r["person_name"].lower())
        and "DESIGNACION" in r["change_type"]
        for r in records
    )

    # Run OCR only if needed and available
    ocr_results = []
    if has_collective:
        try:
            from ocr_extract import ocr_gazette_body, extract_designations_from_ocr, page_needs_ocr
            # Check if this gazette has image-based pages
            doc = fitz.open(pdf_path)
            needs_ocr = any(page_needs_ocr(doc, i) for i in range(1, len(doc) - 1))
            doc.close()
            if needs_ocr:
                print(f"    Running OCR...")
                ocr_text = ocr_gazette_body(pdf_path)
                ocr_results = extract_designations_from_ocr(ocr_text)
                print(f"    OCR found {len(ocr_results)} designations")
        except ImportError:
            pass  # OCR not available
        except Exception as e:
            print(f"    OCR error: {e}")

    # Expand collective SUMARIO entries using body data, enrich named entries, add extras
    used_body = set()

    # First pass: identify collective placeholders and expand them
    is_collective = lambda r: (
        not r["person_name"] or r["person_name"].startswith("y ") or "ciudadan" in r["person_name"].lower()
    ) and "DESIGNACION" in r["change_type"]

    new_records = []
    for r in records:
        if is_collective(r):
            # Find all body entries that belong to this record (by decree number)
            matching_body = []
            if r["decree_number"]:
                matching_body = [bd for bd in body_decrees if bd["decree_number"] == r["decree_number"]]

            if matching_body:
                # Replace the collective placeholder with individual records
                for bd in matching_body:
                    used_body.add(id(bd))
                    ct = classify_change(bd["context"])
                    if ct == "OTRO":
                        ct = r["change_type"]  # inherit from the SUMARIO entry
                    inst = extract_institution(bd["context"])
                    org = r["organism"] or extract_organism(bd["context"], "", bd["post"])
                    new_records.append({
                        "gazette_number": gazette_num,
                        "gazette_type": gazette_type,
                        "gazette_date": date,
                        "decree_number": r["decree_number"],
                        "change_type": ct,
                        "person_name": bd["name"],
                        "post_or_position": bd["post"],
                        "institution": inst,
                        "organism": org,
                        "is_military_person": "SI" if bd["is_military_person"] else "NO",
                        "military_rank": bd["military_rank"],
                        "is_military_post": "SI" if bd["is_military_post"] or is_military_post(org) else "NO",
                        "summary": bd["context"][:500],
                    })
            else:
                # No body matches from text — try OCR if available
                if ocr_results:
                    # Match OCR results to this collective entry by post keywords
                    entry_post = r.get("post_or_position", "").lower()
                    entry_summary = r.get("summary", "").lower()
                    matched_ocr = []
                    for ocr_r in ocr_results:
                        ocr_post = ocr_r.get("post", "").lower()
                        # Match OCR result to this entry if post types align
                        if entry_post and ocr_post:
                            # Check if the OCR post relates to the collective entry
                            if any(kw in ocr_post for kw in ["director", "gerente", "presidente",
                                                              "comisionad", "inspector", "miembro",
                                                              "junta", "fiscal", "contralor"]):
                                if any(kw in entry_post for kw in ["director", "gerente", "presidente",
                                                                    "comisionad", "inspector", "miembro",
                                                                    "junta", "fiscal", "contralor"]):
                                    matched_ocr.append(ocr_r)
                    if matched_ocr:
                        for ocr_r in matched_ocr:
                            ct = classify_change("se designa al ciudadano " + ocr_r["name"] + ", como " + ocr_r["post"])
                            if ct == "OTRO":
                                ct = r["change_type"]
                            new_records.append({
                                "gazette_number": gazette_num,
                                "gazette_type": gazette_type,
                                "gazette_date": date,
                                "decree_number": r["decree_number"],
                                "change_type": ct,
                                "person_name": ocr_r["name"],
                                "post_or_position": ocr_r["post"],
                                "institution": r.get("institution", ""),
                                "organism": r.get("organism", ""),
                                "is_military_person": "NO",
                                "military_rank": "",
                                "is_military_post": "SI" if is_military_post(ocr_r["post"] + " " + r.get("organism", "")) else "NO",
                                "summary": f"[OCR] {ocr_r['name']} como {ocr_r['post']}"[:500],
                            })
                    else:
                        new_records.append(r)
                else:
                    new_records.append(r)
        else:
            new_records.append(r)

    records = new_records

    # Second pass: enrich named SUMARIO records with body data
    for bd in body_decrees:
        if id(bd) in used_body:
            continue
        bd_name_upper = bd["name"].upper().strip()
        matched = False

        for r in records:
            sumario_upper = r.get("summary", "").upper()
            if bd_name_upper and len(bd_name_upper) > 5:
                name_parts = bd_name_upper.split()
                if len(name_parts) >= 2:
                    surname = name_parts[-1] if len(name_parts[-1]) > 3 else name_parts[-2] if len(name_parts) > 2 else name_parts[-1]
                    if surname in sumario_upper:
                        matched = True
                        if not r["person_name"]:
                            r["person_name"] = bd["name"]
                        if not r["post_or_position"] and bd["post"]:
                            r["post_or_position"] = bd["post"]
                        if bd["is_military_person"]:
                            r["is_military_person"] = "SI"
                            r["military_rank"] = bd["military_rank"]
                        if bd["is_military_post"]:
                            r["is_military_post"] = "SI"
                        used_body.add(id(bd))
                        break

        if not matched and id(bd) not in used_body:
            # Additional designation from body not in SUMARIO
            change_type = classify_change(bd["context"])
            if change_type == "OTRO":
                change_type = "DESIGNACION_OTRO"
            institution = extract_institution(bd["context"])
            organism = extract_organism(bd["context"], "", bd["post"])
            records.append({
                "gazette_number": gazette_num,
                "gazette_type": gazette_type,
                "gazette_date": date,
                "decree_number": bd["decree_number"],
                "change_type": change_type,
                "person_name": bd["name"],
                "post_or_position": bd["post"],
                "institution": institution,
                "organism": organism,
                "is_military_person": "SI" if bd["is_military_person"] else "NO",
                "military_rank": bd["military_rank"],
                "is_military_post": "SI" if bd["is_military_post"] else "NO",
                "summary": bd["context"][:500],
            })

    # If no entries found, check for full-gazette content (laws, etc.)
    if not records:
        norm = collapse_ws(text).lower()
        if "ley de reforma" in norm:
            title = ""
            m = re.search(r"(LEY\s+DE\s+REFORMA[^.]+)", collapse_ws(text))
            if m:
                title = m.group(1)[:200]
            records.append(make_record(gazette_num, gazette_type, date,
                                       "REFORMA_LEGISLATIVA", "", "", "", title or "Ley de Reforma",
                                       organism="Asamblea Nacional"))
        elif "ley de amnist" in norm:
            records.append(make_record(gazette_num, gazette_type, date,
                                       "LEY_AMNISTIA", "", "", "",
                                       "Ley de Amnistía para la Convivencia Democrática",
                                       organism="Asamblea Nacional"))
        elif "estado de conmoci" in norm:
            records.append(make_record(gazette_num, gazette_type, date,
                                       "ESTADO_DE_EXCEPCION", "", "", "",
                                       "Decreto de Estado de Conmoción Exterior",
                                       organism="Presidencia de la República"))
        elif "sala constitucional" in norm and "sentencia" in norm:
            records.append(make_record(gazette_num, gazette_type, date,
                                       "SENTENCIA_TSJ", "", "", "Tribunal Supremo de Justicia",
                                       "Sentencia de la Sala Constitucional del TSJ",
                                       organism="Tribunal Supremo de Justicia"))
        elif "tribunal supremo" in norm:
            records.append(make_record(gazette_num, gazette_type, date,
                                       "SENTENCIA_TSJ", "", "", "Tribunal Supremo de Justicia",
                                       "Publicación del Tribunal Supremo de Justicia",
                                       organism="Tribunal Supremo de Justicia"))

    # Final cleanup: fix and clear invalid person names, then deduplicate
    for r in records:
        name = r.get("person_name", "")
        if not name:
            continue

        # Strip title prefixes: Abogado/a, Diputado/a, Principal, SUPLENTES, PRINCIPALES, etc.
        name = re.sub(
            r"^(?:Abogad[oa]|Diputad[oa]|Principal(?:es)?|Suplentes?)\s+",
            "", name, flags=re.IGNORECASE
        ).strip()

        # Strip "DE LA JUNTA" prefix (OCR artifact — keep the actual name after it)
        name = re.sub(r"^DE\s+LA\s+JUNTA\s+", "", name).strip()

        # Clear names that are institution names, not person names
        if re.match(r"^(?:DE\s+LA\s+|DEL\s+|DE\s+LOS\s+|LA\s+)", name, re.IGNORECASE):
            name = ""
        if re.match(r"^(?:del\s+Instituto|Fundaci|Corporaci|Instituto|Servicio)", name, re.IGNORECASE):
            name = ""

        # Clear "que en ella se mencionan/indican" garbage
        if re.search(r"que\s+en\s+(?:ella|[eé]l)\s+se\s+(?:mencionan|indican|se[ñn]alan)", name, re.IGNORECASE):
            name = ""

        # Clear names that are just noise words
        if name.upper() in ["PRINCIPAL", "SUPLENTE", "MIEMBRO", "SUPLENTES", "PRINCIPALES"]:
            name = ""

        # Clear invalid short names or starting with "y "
        if name and (name.startswith("y ") or name.lower().startswith("y ") or
                     "ciudadan" in name.lower() or len(name) <= 2):
            name = ""

        r["person_name"] = name

    # Deduplicate and remove empty OCR entries
    seen = set()
    unique_records = []
    for r in records:
        name_upper = r.get("person_name", "").upper().strip()
        is_ocr = r.get("summary", "").startswith("[OCR]")

        # Remove OCR entries that ended up with no person name (noise)
        if is_ocr and not name_upper:
            continue

        # Remove OCR entries that duplicate text-parsed entries
        if name_upper and is_ocr:
            if name_upper in seen:
                continue

        if name_upper:
            seen.add(name_upper)
        unique_records.append(r)

    return unique_records


def make_record(gnum, gtype, date, change_type, person, post, institution, summary, organism=""):
    return {
        "gazette_number": gnum,
        "gazette_type": gtype,
        "gazette_date": date,
        "decree_number": "",
        "change_type": change_type,
        "person_name": person,
        "post_or_position": post,
        "institution": institution,
        "organism": organism,
        "is_military_person": "NO",
        "military_rank": "",
        "is_military_post": "NO",
        "summary": summary[:500],
    }


# ─── Casing normalization ────────────────────────────────────────────

# Spanish lowercase words that should NOT be capitalized in titles (unless first word)
_LOWERCASE_WORDS = {
    "de", "del", "la", "el", "las", "los", "y", "e", "en", "para", "por",
    "con", "al", "a", "su", "sus", "un", "una", "o", "que", "se", "lo",
}

# Known acronyms that must stay uppercase
_ACRONYMS = {
    "ASIC", "SENIAT", "INATUR", "INPSASEL", "INAC", "INAPYMI", "FONACIT",
    "CONVIASA", "CORPOELEC", "CUSPAL", "VENETUR", "VENTEL", "VENVIDRIO",
    "FONDOIN", "COVEPLAST", "CORSOVENCA", "IAIM", "SEDEFANB", "CEOFANB",
    "DGCIM", "INSAMONAGAS", "CORPOSALUD", "FUNDASALUD", "IPOSTEL",
    "IVSS", "INCRET", "BCV", "TSJ", "CICPC", "FANB", "UCS", "IEU",
    "IUDAG", "IUTSO", "IUTA", "IUTECP", "HIDROVEN", "VTV", "OPPPE",
    "BAER", "IAIM", "EANSA", "SM", "SACS", "SUDEBAN", "FONCINE",
    "DMS", "AGROFLORA", "SIDUNEA", "C.A.", "C.A", "S.A.", "S.A",
    "CCIA", "CMAE", "COVENIN", "R.S.", "R.I.F.", "II", "III", "IV",
    "N°", "Nº", "N.", "(E)", "(E", "E)", "PSUV",
    "CSC", "DIANCA", "TROMERCA", "SAINGO", "SATA",
    "CENDITEL", "CENIDIC", "FUNDEEH",
    "CORPOASFALTO", "CORPOSALUD",
    "CONGLOMERADO", "PSC",
}

# Roman numerals and ordinals that should stay as-is
_KEEP_UPPER = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}


def _spanish_title_case(text):
    """Convert text to Spanish title case.
    - First word always capitalized
    - Small words (de, del, la, el, y, en, para, etc.) stay lowercase
    - Acronyms stay uppercase
    - Words in quotes/parentheses keep their case for acronyms
    """
    if not text:
        return text

    words = text.split()
    result = []

    for i, word in enumerate(words):
        # Check if the whole word (or stripped version) is an acronym
        stripped = word.strip(".,;:()\"«»'")
        if stripped.upper() in _ACRONYMS or stripped in _KEEP_UPPER:
            result.append(word.upper() if stripped.upper() == stripped else word)
            continue

        # If word is ALL UPPERCASE and has dots (like C.A. or S.A.)
        if "." in word and word == word.upper():
            result.append(word)
            continue

        # Parenthetical content: "(CORPOSALUD)" stays upper
        if word.startswith("(") and word.upper().strip("()") in _ACRONYMS:
            result.append(word.upper())
            continue

        # Convert word to title case
        lower_word = word.lower()
        # Strip punctuation for checking
        bare = lower_word.strip(".,;:()\"«»'")

        if i == 0:
            # First word always capitalized
            result.append(word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper())
        elif bare in _LOWERCASE_WORDS:
            result.append(lower_word)
        else:
            # Capitalize first letter, lowercase rest
            # But preserve internal caps for names like "D'Onofrio"
            if "'" in word or "\u2019" in word or "\u00b4" in word:
                # Name with apostrophe: capitalize after apostrophe too
                parts = re.split(r"([''\u2019\u00b4])", word)
                titled = ""
                for j, part in enumerate(parts):
                    if j == 0 or (j > 0 and parts[j-1] in "''\u2019\u00b4"):
                        titled += part.capitalize()
                    else:
                        titled += part
                result.append(titled)
            else:
                result.append(word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper())

    text_out = " ".join(result)

    # Post-process: fix (e) -> (E) for "Encargado/a", and capitalize words in parentheses
    text_out = re.sub(r'\(e\)', '(E)', text_out)
    text_out = re.sub(r'\(encargad[oa]\)', lambda m: m.group(0).title(), text_out, flags=re.IGNORECASE)
    # Fix common parenthetical acronyms that got lowercased
    def _upper_parens(m):
        inner = m.group(1).upper()
        return f"({inner})"
    text_out = re.sub(r'\(([a-záéíóúñü]{2,10})\)', lambda m: f"({m.group(1).upper()})" if m.group(1).upper() in _ACRONYMS else m.group(0), text_out)

    return text_out


def _normalize_name(name):
    """Normalize person name to Title Case."""
    if not name:
        return name
    return _spanish_title_case(name)


def _normalize_post(post):
    """Normalize post/position to Title Case."""
    if not post:
        return post
    return _spanish_title_case(post)


def _normalize_organism(org):
    """Normalize organism — Title Case but keep acronyms in parentheses uppercase."""
    if not org:
        return org

    # Split on parenthetical acronyms: "Fiscalía X (MINISTERIO DEL PODER POPULAR...)"
    m = re.match(r"^(.+?)\s*\((.+)\)\s*$", org)
    if m:
        main_part = _spanish_title_case(m.group(1))
        parent_part = _spanish_title_case(m.group(2))
        return f"{main_part} ({parent_part})"

    return _spanish_title_case(org)


def normalize_record_casing(r):
    """Normalize all text fields in a record to consistent casing."""
    r["person_name"] = _normalize_name(r.get("person_name", ""))
    r["post_or_position"] = _normalize_post(r.get("post_or_position", ""))
    r["institution"] = _normalize_organism(r.get("institution", ""))
    r["organism"] = _normalize_organism(r.get("organism", ""))


def _last_gazette_numbers(csv_path):
    """Return the highest gazette number seen per type in an existing CSV.
    Returns a dict like {"Ordinaria": 43310, "Extraordinaria": 6970}.
    Missing types default to 0.
    """
    last = {"Ordinaria": 0, "Extraordinaria": 0}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            gtype = row.get("gazette_type", "")
            try:
                num = int(row.get("gazette_number", 0))
            except ValueError:
                continue
            if gtype in last and num > last[gtype]:
                last[gtype] = num
    return last


def main():
    parser = argparse.ArgumentParser(description="Extract government changes from gazette PDFs.")
    parser.add_argument("--output", default="cambios_gobierno.csv", help="Output CSV filename (default: cambios_gobierno.csv)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    ord_dir = os.path.join(base_dir, "Gacetas_2026_Ordinaria")
    ext_dir = os.path.join(base_dir, "Gacetas_2026_Extraordinaria")

    # If the output file already exists, find the last processed gazette per type
    # and skip everything up to and including that number.
    csv_path = os.path.join(base_dir, args.output)
    start_after = {"Ordinaria": 0, "Extraordinaria": 0}
    if os.path.exists(csv_path):
        start_after = _last_gazette_numbers(csv_path)
        for gtype, num in start_after.items():
            if num:
                print(f"Resuming {gtype} from gazette {num + 1} (last seen: {num})")

    all_records = []

    for folder, gtype in [(ord_dir, "Ordinaria"), (ext_dir, "Extraordinaria")]:
        if not os.path.exists(folder):
            print(f"Folder not found: {folder}")
            continue
        for f in sorted(os.listdir(folder)):
            if f.endswith(".pdf"):
                num = f.replace("Gaceta_", "").replace(".pdf", "")
                if int(num) <= start_after.get(gtype, 0):
                    continue
                path = os.path.join(folder, f)
                print(f"Processing {gtype} {num}...")
                try:
                    records = process_gazette(path, num, gtype)
                    all_records.extend(records)
                    print(f"  -> {len(records)} entries found")
                except Exception as e:
                    import traceback
                    print(f"  -> ERROR: {e}")
                    traceback.print_exc()

    # Post-process: clean up post/institution/organism relationships
    for r in all_records:
        post = r.get("post_or_position", "")
        change = r.get("change_type", "")
        inst = r.get("institution", "")
        org = r.get("organism", "")

        # ── Fix fiscal posts: extract institution from post ──
        if post and ("FISCAL" in change or "TRASLADO_FISCAL" in change):
            # First, remove person name leaked into post:
            # "Fiscal Auxiliar Interino al Ciudadano Jesús..., en la Fiscalía..."
            # "Fiscal Provisorio a la Ciudadana Name, en la Fiscalía..."
            post = re.sub(
                r"(Fiscal\s+\w+(?:\s+\w+)?)\s+(?:al\s+Ciudadano|a\s+la\s+Ciudadana)\s+[^,]+?,\s*(?:en|a)\s+(?:la|el)\s+",
                r"\1 en la ",
                post, flags=re.IGNORECASE
            )
            # Also: "Fiscal Auxiliar Superior de Investigación al Ciudadano Name, en la..."
            post = re.sub(
                r"(Fiscal\s+Auxiliar\s+Superior\s+de\s+Investigaci[oó]n)\s+(?:al\s+Ciudadano|a\s+la\s+Ciudadana)\s+[^,]+?,\s*(?:en|a)\s+la\s+",
                r"\1 en la ",
                post, flags=re.IGNORECASE
            )

            # Split post into role + institution: "Fiscal Auxiliar Interino a/en la Fiscalía XXX..."
            m = re.match(
                r"(Fiscal\s+(?:Auxiliar\s+(?:Interino|Superior\s+de\s+Investigaci[oó]n)|Provisori[oa]?))"
                r"\s+(?:a\s+la|en\s+la)\s+(Fiscal[ií]a\s+.+)",
                post, re.IGNORECASE
            )
            if m:
                r["post_or_position"] = m.group(1).strip()
                fiscalia = m.group(2).strip()
                # Clean trailing noise from fiscalía
                fiscalia = re.sub(r"\s*,\s*(?:con\s+sede|con\s+competencia).*$", "", fiscalia)
                r["institution"] = fiscalia
            # Also handle: "Fiscal Provisorio en la Fiscalía..."
            else:
                m2 = re.match(
                    r"(Fiscal\s+Provisori[oa]?)"
                    r"\s+en\s+la\s+(Fiscal[ií]a\s+.+)",
                    post, re.IGNORECASE
                )
                if m2:
                    r["post_or_position"] = m2.group(1).strip()
                    fiscalia = m2.group(2).strip()
                    fiscalia = re.sub(r"\s*,\s*(?:con\s+sede|con\s+competencia).*$", "", fiscalia)
                    r["institution"] = fiscalia
            # Also handle Sala de Flagrancia / Unidad de Depuración
            post_now = r.get("post_or_position", "")
            if "Fiscal" in post_now and ("Sala" in post_now or "Unidad" in post_now):
                m3 = re.match(
                    r"(Fiscal\s+Auxiliar\s+Interino)"
                    r"\s+(?:en\s+la|a\s+la)\s+((?:Sala|Unidad)\s+.+)",
                    post_now, re.IGNORECASE
                )
                if m3:
                    r["post_or_position"] = m3.group(1).strip()
                    inst = m3.group(2).strip()
                    inst = re.sub(r"\s*,\s*(?:adscrit|del\s+Minister).*$", "", inst)
                    r["institution"] = inst

            # Always set organism to Ministerio Público for fiscal entries
            r["organism"] = "Ministerio Público"

        # ── Fix any designation with wrong organism (fiscal entries under IPOSTEL etc.) ──
        if "FISCAL" in change and "Ministerio P" not in r.get("organism", ""):
            if "fiscal" in r.get("post_or_position", "").lower() or "fiscal" in r.get("institution", "").lower():
                r["organism"] = "Ministerio Público"

    # Normalize casing for publication
    for r in all_records:
        normalize_record_casing(r)

    # Second pass cleanup: fix remaining fiscal posts AFTER normalization
    for r in all_records:
        post = r.get("post_or_position", "")
        change = r.get("change_type", "")
        if post and ("FISCAL" in change or "TRASLADO" in change):
            # Remove "al Ciudadano Name," or "a la Ciudadana Name," from post
            new_post = re.sub(
                r"(Fiscal\s+\w+(?:\s+\w+)?)\s+(?:al\s+Ciudadano|a\s+la\s+Ciudadana)\s+[^,]+?,\s*(?:en|a)\s+(?:la|el)\s+",
                r"\1 en la ",
                post, flags=re.IGNORECASE
            )
            if new_post != post:
                r["post_or_position"] = new_post
                # Now split into post + institution
                m = re.match(
                    r"(Fiscal\s+(?:Auxiliar\s+(?:Interino|Superior\s+de\s+Investigaci[oó]n)|Provisori[oa]?))"
                    r"\s+(?:en\s+la|a\s+la)\s+(.+)",
                    new_post, re.IGNORECASE
                )
                if m:
                    r["post_or_position"] = m.group(1).strip()
                    inst = m.group(2).strip()
                    inst = re.sub(r"\s*,\s*(?:con\s+sede|con\s+competencia).*$", "", inst)
                    inst = re.sub(r"\s+del\s+Ministerio\s+P.*$", "", inst)
                    r["institution"] = inst
                    r["organism"] = "Ministerio Público"
                    # Re-normalize the cleaned fields
                    normalize_record_casing(r)

    # Write CSV
    fieldnames = [
        "gazette_number", "gazette_type", "gazette_date", "decree_number",
        "change_type", "person_name", "post_or_position", "institution",
        "organism",
        "is_military_person", "military_rank", "is_military_post", "summary",
    ]

    file_exists = os.path.exists(csv_path)

    # Load existing keys to avoid duplicates when appending
    existing_keys = set()
    if file_exists:
        with open(csv_path, newline="", encoding="utf-8-sig") as existing_csv:
            reader = csv.DictReader(existing_csv)
            for row in reader:
                key = (row.get("gazette_number"), row.get("gazette_type"), row.get("person_name"), row.get("change_type"))
                existing_keys.add(key)

    new_records = [
        r for r in all_records
        if (r.get("gazette_number"), r.get("gazette_type"), r.get("person_name"), r.get("change_type")) not in existing_keys
    ]

    with open(csv_path, "a" if file_exists else "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in new_records:
            writer.writerow(r)

    if file_exists:
        print(f"\nDone! {len(new_records)} new records appended to {csv_path} ({len(all_records) - len(new_records)} duplicates skipped)")
    else:
        print(f"\nDone! {len(new_records)} total records written to {csv_path}")

    # Summary statistics
    types = {}
    for r in all_records:
        t = r["change_type"]
        types[t] = types.get(t, 0) + 1

    print("\n=== SUMMARY BY CHANGE TYPE ===")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    mil_persons = sum(1 for r in all_records if r["is_military_person"] == "SI")
    mil_posts = sum(1 for r in all_records if r["is_military_post"] == "SI")
    named = sum(1 for r in all_records if r["person_name"])
    print(f"\nRecords with person name: {named}")
    print(f"Military persons: {mil_persons}")
    print(f"Military posts: {mil_posts}")


if __name__ == "__main__":
    main()
