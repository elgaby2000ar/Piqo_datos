"""Clasificación de productos por tipo, a partir del nombre.

SEPA no informa categorías, así que se infieren con reglas simples y explicables:
cada categoría tiene frases clave que tienen que coincidir con el comienzo de
palabras del nombre normalizado. Las reglas se evalúan en orden y gana la primera,
por eso las más específicas van antes ("jabon en polvo" es limpieza antes de que
"jabon" lo mande a perfumería).

Es deliberadamente simple: cuando haya volumen, las correcciones de la comunidad
y un clasificador entrenado pueden reemplazar estas reglas sin cambiar la API.
"""

from dataclasses import dataclass

from app.normalizacion import normalizar_texto


@dataclass(frozen=True)
class Categoria:
    slug: str
    nombre: str
    frases: tuple[str, ...]


# Frases relevadas sobre los 81.456 productos distintos del archivo real de SEPA del
# 16/11/2026, incluidas las abreviaturas que usan las cadenas ("sha", "acond", "yog").
# Una frase con espacio final ("pan ", "te ") exige palabra completa: así "pan" no
# encuentra "pantalon" ni "te" encuentra "termo".
CATEGORIAS: tuple[Categoria, ...] = (
    Categoria(
        "limpieza",
        "Limpieza",
        ("jabon en polvo", "jabon liquido para ropa", "detergente", "deterg", "lavandina",
         "suavizante", "limpiador", "limp ", "limpia", "desengrasante", "lustramuebles",
         "insecticida", "esponja", "trapo", "rejilla", "pano", "lavavajilla", "quitamancha",
         "desinfectante", "aromatizante", "aromatizador", "aromat", "cera ", "bolsa de residuo",
         "bolsas de residuo", "removedor", "sarro", "microfibra", "escobillon", "escoba", "mopa",
         "secador de piso", "balde"),
    ),
    Categoria(
        "perfumeria",
        "Perfumería",
        ("shampoo", "sha ", "acondicionador", "acond", "jabon", "jab ", "desodorante", "desod",
         "deo ", "pasta dental", "crema dental", "cepillo dental", "cepillo de dientes",
         "enjuague bucal", "papel higienico", "panal", "toallita", "toalla", "toallas",
         "siempre libre", "always ", "toallas humedas", "afeitar", "maquinita", "protector solar",
         "coloracion", "tintura", "esmalte", "crema corporal", "crema facial", "crema para manos",
         "agua micelar", "agua oxigenada", "algodon", "hisopo", "preservativo", "gel de ducha",
         "gel fijador", "repelente", "talco", "peine", "balsamo", "crema de peinar",
         "crema p pein", "aco ", "cortaunas", "tampon", "pedico"),
    ),
    Categoria(
        "lacteos",
        "Lácteos",
        ("leche", "yogur", "yog ", "queso", "manteca", "crema de leche", "dulce de leche",
         "postre", "flan", "ques ", "nidina", "nutrilon", "sancor bebe", "ricota", "muzzarella",
         "mozzarella"),
    ),
    Categoria(
        "bebidas",
        "Bebidas",
        ("gaseosa", "agua ", "jugo", "cerveza", "vino ", "vinos", "soda", "fernet", "aperitivo",
         "bebida", "energizante", "sidra", "whisky", "gin ", "vodka", "licor", "espumante",
         "champagne", "ron ", "vermouth", "isotonica", "amargo", "levite", "baggio", "citric",
         "h2oh", "cepita", "ades ", "tang ", "clight", "coca cola", "pepsi", "sprite", "fanta",
         "7up", "quilmes", "brahma", "stella artois", "schneider", "villavicencio",
         "villa del sur", "eco de los andes", "glaciar", "powerade", "gatorade", "speed ",
         "monster", "red bull", "7 up", "ginebra", "fizz", "beb "),
    ),
    Categoria(
        "carnes",
        "Carnes y fiambres",
        ("carne", "pollo", "milanesa", "hamburguesa", "salchicha", "jamon", "salame", "salamin",
         "mortadela", "fiambre", "bife ", "bifes", "asado", "cerdo", "pescado", "atun", "merluza",
         "vacio", "matambre", "entrana", "nalga", "peceto", "cuadril", "osobuco", "costilla",
         "picada", "molida", "lomo", "bondiola", "chorizo", "morcilla", "medallon", "pechuga",
         "suprema", "pata muslo", "nugget", "roast beef", "paleta de cerdo"),
    ),
    Categoria(
        "golosinas",
        "Golosinas y snacks",
        ("alfajor", "chocolate", "choc ", "bombon", "caramelo", "caram ", "gomitas", "chicle",
         "chupetin", "turron", "oblea", "barra de cereal", "barrita", "mani ", "snack",
         "papas fritas", "palitos", "confite", "pastillas", "helado", "minitorta", "brownie",
         "bocadito", "barra ", "extrafino"),
    ),
    Categoria(
        "frutas_verduras",
        "Frutas y verduras",
        ("papa ", "papas ", "batata", "tomate fresco", "cebolla", "zanahoria", "lechuga", "banana",
         "manzana", "naranja", "mandarina", "limon", "zapallo", "huevo", "ajo "),
    ),
    Categoria(
        "panaderia",
        "Panadería",
        ("pan ", "panes", "pan de", "facturas", "medialuna", "bizcocho", "budin", "torta",
         "tostadas", "grisin", "baguet", "flautita", "felipe", "prepizza", "pizza",
         "tapa de empanada", "tapas para"),
    ),
    Categoria(
        "almacen",
        "Almacén",
        ("yerba", "arroz", "fideo", "fid ", "harina", "aceite", "azucar", "cafe", "te ",
         "mate cocido", "galletita", "galleta", "gall ", "pure de tomate", "tomate triturado",
         "sal ", "lenteja", "poroto", "garbanzo", "arveja", "mayonesa", "ketchup", "mostaza",
         "vinagre", "aceto", "polenta", "cacao", "mermelada", "merm ", "edulcorante", "endulzante",
         "caldo", "sopa", "conserva", "choclo", "salsa", "aderezo", "aceituna", "avena", "miel",
         "pasta", "maiz", "granola", "pimienta", "condimento", "oregano", "pimenton", "gelatina",
         "premezcla", "bizcochuelo", "noqui", "raviol", "sorrentino", "capeletti", "tallarin",
         "canelon", "lasagna", "dulce de batata", "dulce batata", "dulce de membrillo",
         "pulpa de tomate", "pulpa tomate", "nuez moscada", "romero", "durazno en", "duraznos en",
         "especia"),
    ),
    Categoria(
        "mascotas",
        "Mascotas",
        ("perro", "gato ", "gatos", "cachorro", "dog chow", "cat chow", "pedigree", "whiskas",
         "piedras sanitarias", "arena sanitaria"),
    ),
    Categoria(
        "bazar",
        "Bazar y hogar",
        ("vaso", "plato", "bowl", "taza", "mug ", "jarro", "jarra", "copa", "sarten", "cacerola",
         "olla", "bandeja", "fuente", "tabla", "cuchara", "cuchillo", "tenedor", "hermetico",
         "contenedor", "toalla de mano", "toalla de bano", "toallon", "repasador", "mantel",
         "sabana", "acolchado", "frazada", "almohad", "cortina", "vela", "sahumerio", "difusor",
         "adorno", "maceta", "florero", "cesto", "canasto", "organizador", "lampara", "foco",
         "pila ", "pilas"),
    ),
)

OTROS = Categoria("otros", "Otros", ())
POR_SLUG: dict[str, Categoria] = {c.slug: c for c in (*CATEGORIAS, OTROS)}


def _posicion(texto: str, frase: str) -> int | None:
    """Dónde empieza la frase, solo si arranca al comienzo de una palabra
    y termina en un final de palabra o de prefijo ("fideo" encuentra "fideos")."""
    texto = f"{texto} "  # una frase de palabra completa también coincide al final
    if texto.startswith(frase):
        return 0
    indice = texto.find(f" {frase}")
    return indice + 1 if indice >= 0 else None


def clasificar(nombre: str) -> str:
    """En español el sustantivo principal suele ir primero ("Caldo de pollo",
    "Jabón en polvo"), así que gana la frase que aparece antes en el nombre.
    Si dos frases empiezan en el mismo lugar gana la más larga, que es la más
    específica ("toalla de mano" le gana a "toalla"). Si siguen empatadas, gana la
    categoría que figura primero en CATEGORIAS."""
    texto = normalizar_texto(nombre)
    mejor: tuple[int, int, int] | None = None  # (posición, -largo de la frase, orden)
    elegida = OTROS.slug
    for orden, categoria in enumerate(CATEGORIAS):
        coincidencias = [
            (p, -len(f)) for f in categoria.frases if (p := _posicion(texto, f)) is not None
        ]
        if not coincidencias:
            continue
        candidata = (*min(coincidencias), orden)
        if mejor is None or candidata < mejor:
            mejor, elegida = candidata, categoria.slug
    return elegida
