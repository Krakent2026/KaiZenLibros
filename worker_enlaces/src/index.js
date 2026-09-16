/**
 * Enlace universal geolocalizado — Cloudflare Worker (plan gratuito).
 *
 *   https://enlaces.tudominio.es/no-es-pereza?c=ig
 *     → https://www.amazon.<tienda del país>/dp/<ASIN>?utm_source=instagram&utm_medium=social&utm_campaign=no-es-pereza
 *
 * - Sin ASIN todavía: redirige a una búsqueda en Amazon por título y autor.
 * - /mente-distinta (alias de serie) → libro 1 de la serie.
 * - / → web del sello.
 * - ?c=<canal corto> se traduce a utm_source con la tabla del YAML (ig→instagram...).
 * - Si existe el binding CLICS (Analytics Engine, gratuito), registra slug, país y canal. Sin datos personales.
 */
import enlaces from "../enlaces.json";

const UTM_PERMITIDAS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];

function tiendaPara(pais) {
  return enlaces.marketplaces[pais] || enlaces.por_defecto;
}

function destino(libro, tienda, utm) {
  const params = new URLSearchParams(utm);
  const tag = enlaces.afiliados[tienda];
  if (tag) params.set("tag", tag);
  if (libro.asin_ebook) {
    return `https://www.${tienda}/dp/${libro.asin_ebook}?${params}`;
  }
  params.set("k", decodeURIComponent(libro.busqueda.replace(/\+/g, " ")));
  params.set("i", "digital-text");
  return `https://www.${tienda}/s?${params}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const slug = url.pathname.replace(/^\/+|\/+$/g, "");

    if (!slug) {
      return Response.redirect(enlaces.web + "/", 302);
    }
    if (slug === "salud") {
      return new Response("ok", { headers: { "content-type": "text/plain" } });
    }

    const libro = enlaces.libros[slug];
    if (!libro) {
      return new Response("Enlace no encontrado", { status: 404 });
    }

    const pais = (request.cf && request.cf.country) || "XX";
    const tienda = tiendaPara(pais);
    const canalCorto = url.searchParams.get("c") || "";
    const fuente = enlaces.canales[canalCorto] || canalCorto || "directo";

    const utm = {
      utm_source: fuente,
      utm_medium: url.searchParams.get("m") || enlaces.utm_medium,
      utm_campaign: url.searchParams.get("k") || (libro.alias_de || slug),
    };
    for (const clave of UTM_PERMITIDAS) {
      const v = url.searchParams.get(clave);
      if (v) utm[clave] = v;
    }

    if (env.CLICS) {
      try {
        env.CLICS.writeDataPoint({
          blobs: [libro.alias_de || slug, pais, fuente, tienda],
          doubles: [1],
          indexes: [libro.alias_de || slug],
        });
      } catch (_) {
        // el registro nunca debe romper la redirección
      }
    }

    return Response.redirect(destino(libro, tienda, utm), 302);
  },
};
