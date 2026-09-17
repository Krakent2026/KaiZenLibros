from agentes.guardian.reglas import bloquea, revisar
from agentes.guardian.verificar_citas import localizar, normalizar


def test_bloquea_promesas_de_salud():
    assert bloquea(revisar("Este libro cura la ansiedad en tres semanas."))
    assert bloquea(revisar("Reduce el estrés y mejora tu concentración."))
    assert bloquea(revisar("El bestseller que transforma tu vida."))
    assert bloquea(revisar("Descubre si tienes TDAH con este test de TDAH."))


def test_no_bloquea_lo_legitimo():
    assert not bloquea(revisar("Este libro explica de qué trata el TDAH adulto y por qué no es falta de voluntad."))
    assert not bloquea(revisar("Por qué el TDAH no se cura, por mucho que se lo prometan a la gente."))
    assert not bloquea(revisar("No es pereza: es atención que no obedece."))


def test_negacion_atenua_a_aviso():
    # la voz de la casa se define por negaciones: no pueden bloquearse
    for frase in ("En ningún libro se diagnostica, se predice ni se promete nada.",
                  "Aquí nadie tiene un superpoder ni una avería: hay sistemas.",
                  "Ni un test. Ni una vez «es un superpoder».",
                  "Este libro no cura la ansiedad y lo dice en la primera página."):
        h = revisar(frase)
        assert h and not bloquea(h), frase
    # la misma palabra sin negación sigue bloqueando
    assert bloquea(revisar("Este libro predice tu futuro."))
    assert bloquea(revisar("Tu TDAH es un superpoder."))
    # la negación no cruza el punto: la frase siguiente se evalúa sola
    assert bloquea(revisar("No hay atajos. Este método cura la ansiedad."))


def test_avisa_sin_bloquear():
    h = revisar("Hoy el Libro 1 está gratis en Kindle hasta el domingo.")
    assert h and not bloquea(h)
    assert any(x.nivel == "avisa" for x in h)


def test_ingles():
    assert bloquea(revisar("This book heals your brain.", idioma="en"))
    assert not bloquea(revisar("A book about adult ADHD, written without tests or promises.", idioma="en"))


def test_normalizar_equivalencias():
    assert normalizar("«Hola»  —dijo—\n\n*fuerte*") == '"hola" -dijo- fuerte'


def test_localizar_tolerante():
    texto = "Primera línea.\n\nLa **atención** no obedece aunque sepas —perfectamente— lo que tienes que hacer.\n"
    loc = localizar('la atención no obedece aunque sepas –perfectamente– lo que tienes que hacer', texto)
    assert loc is not None
    assert texto[loc.inicio:loc.fin].startswith("La **atención**")
    assert loc.fragmento.endswith("hacer")


def test_localizar_no_inventa():
    assert localizar("esta frase no está en el texto", "Un texto cualquiera, breve.") is None
    assert localizar("corto", "corto") is None  # por debajo del mínimo
