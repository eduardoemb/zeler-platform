/**
 * Devuelve una tabla de publicaciones actuales de ZelerData.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {string} tipo_almacenamiento Filtro de almacenamiento; use "todos" para incluir todos.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} imagen Tipo de imagen a incluir, o vacío para omitir imágenes.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de publicaciones calculada por ZelerData.
 * @customfunction
 */
function ZELERDATA_PUBLICACIONES(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", imagen="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PUBLICACIONES", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, imagen: imagen, encabezados: encabezados });
}
/**
 * Devuelve la lista de SKUs disponibles para la cuenta ZelerData.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @return {Object[][]} Lista de SKUs calculada por ZelerData.
 * @customfunction
 */
function ZELERDATA_SKU(cuenta, skus="todos") {
  return zelerdataExecute_("ZELERDATA_SKU", cuenta, { skus: skus });
}
/**
 * Devuelve IDs de publicación para los SKUs indicados.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @return {Object[][]} Filas con IDs de publicación.
 * @customfunction
 */
function ZELERDATA_ID(cuenta, skus="todos") {
  return zelerdataExecute_("ZELERDATA_ID", cuenta, { skus: skus });
}
/**
 * Devuelve el stock por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas de stock calculadas por ZelerData.
 * @customfunction
 */
function ZELERDATA_STOCK(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_STOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
/**
 * Devuelve el título actual de cada publicación indicada.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con títulos de publicaciones.
 * @customfunction
 */
function ZELERDATA_TITULO(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_TITULO", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve la URL actual por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con URLs de publicaciones.
 * @customfunction
 */
function ZELERDATA_URL(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_URL", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
/**
 * Devuelve el precio seleccionado por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @return {Object[][]} Filas con precios calculados por ZelerData.
 * @customfunction
 */
function ZELERDATA_PRECIO(cuenta, skus, id_publicaciones, tipo_precio="base") {
  return zelerdataExecute_("ZELERDATA_PRECIO", cuenta, { skus: skus, id_publicaciones: id_publicaciones, tipo_precio: tipo_precio });
}
/**
 * Devuelve una tabla de IDs de publicación y stock para los SKUs indicados.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla con SKU, ID de publicación y stock.
 * @customfunction
 */
function ZELERDATA_IDSTOCK(cuenta, skus, encabezados="") {
  return zelerdataExecute_("ZELERDATA_IDSTOCK", cuenta, { skus: skus, encabezados: encabezados });
}
/**
 * Devuelve el estado actual de cada publicación indicada.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con estados de publicaciones.
 * @customfunction
 */
function ZELERDATA_STATUS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_STATUS", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve días pausados por ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con días pausados.
 * @customfunction
 */
function ZELERDATA_PAUSADAS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_PAUSADAS", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve el código de inventario o Mercado Libre por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con códigos ML o de inventario.
 * @customfunction
 */
function ZELERDATA_CODIGOML(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_CODIGOML", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
/**
 * Devuelve cantidades recomendadas para enviar a Full.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} codes Código, lista o rango de códigos.
 * @return {Object[][]} Tabla de recomendaciones de envío a Full.
 * @customfunction
 */
function ZELERDATA_ENVIARAFULL(cuenta, codes) {
  return zelerdataExecute_("ZELERDATA_ENVIARAFULL", cuenta, { codes: codes });
}
/**
 * Convierte códigos ML o de inventario a IDs de publicación y SKUs.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} codigo_ml Código ML, lista o rango de códigos.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla con código, ID de publicación y SKU.
 * @customfunction
 */
function ZELERDATA_CODIGOML2SKUID(cuenta, codigo_ml, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CODIGOML2SKUID", cuenta, { codigo_ml: codigo_ml, encabezados: encabezados });
}
/**
 * Devuelve la cantidad de días desde que cada publicación fue creada.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con días publicada.
 * @customfunction
 */
function ZELERDATA_DIASPUBLICADA(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_DIASPUBLICADA", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve publicaciones Full descuidadas según el tipo de precio seleccionado.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de publicaciones descuidadas.
 * @customfunction
 */
function ZELERDATA_PUBLICACIONESDESCUIDADAS(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PUBLICACIONESDESCUIDADAS", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve métricas de catálogo y buy box.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de métricas de catálogo.
 * @customfunction
 */
function ZELERDATA_CATALOGO(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGO", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve el dashboard de publicaciones actuales.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {string} tipo_almacenamiento Filtro de almacenamiento; use "todos" para incluir todos.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de dashboard calculada por ZelerData.
 * @customfunction
 */
function ZELERDATA_DASHBOARD(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DASHBOARD", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve tiempos de publicaciones sin stock.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de tiempos sin stock.
 * @customfunction
 */
function ZELERDATA_TIEMPOSINSTOCK(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_TIEMPOSINSTOCK", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve el tiempo activa por ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con tiempo activa.
 * @customfunction
 */
function ZELERDATA_TIEMPOACTIVA(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_TIEMPOACTIVA", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve recomendaciones de catálogos sin vincular.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de catálogos sin vincular.
 * @customfunction
 */
function ZELERDATA_CATALOGOSINVINCULAR(cuenta, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOSINVINCULAR", cuenta, { encabezados: encabezados });
}
/**
 * Devuelve información de competencia y buy box de catálogo.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de catálogo buy box.
 * @customfunction
 */
function ZELERDATA_CATALOGOBUYBOX(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOBUYBOX", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve comisiones, cargos y costos de envío por publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de comisiones y cargos.
 * @customfunction
 */
function ZELERDATA_COMISION(cuenta, id_publicaciones, encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMISION", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve devoluciones dentro de un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicio Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de devoluciones.
 * @customfunction
 */
function ZELERDATA_DEVOLUCIONES(cuenta, fecha_inicio, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DEVOLUCIONES", cuenta, { fecha_inicio: fecha_inicio, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve información de competidores por publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de competencia.
 * @customfunction
 */
function ZELERDATA_COMPETENCIA(cuenta, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMPETENCIA", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve métricas de tiempo en catálogo para un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de métricas de catálogo por tiempo.
 * @customfunction
 */
function ZELERDATA_CATALOGOTIEMPO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOTIEMPO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve histórico de precios por publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de histórico de precios.
 * @customfunction
 */
function ZELERDATA_PRECIOHISTORICO(cuenta, id_publicaciones="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PRECIOHISTORICO", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve métricas de tiempo con stock activo para un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de tiempo con stock activo.
 * @customfunction
 */
function ZELERDATA_TIEMPOSTOCKACTIVO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_TIEMPOSTOCKACTIVO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve el dashboard excluyendo publicaciones con indicadores de catálogo.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {string} tipo_almacenamiento Filtro de almacenamiento; use "todos" para incluir todos.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "base".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de dashboard sin catálogo.
 * @customfunction
 */
function ZELERDATA_DASHBOARDSINCATALOGO(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DASHBOARDSINCATALOGO", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve métricas de calidad o salud de publicaciones.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de calidad de publicaciones.
 * @customfunction
 */
function ZELERDATA_CALIDAD(cuenta, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CALIDAD", cuenta, { encabezados: encabezados });
}
/**
 * Devuelve datos de calculadora de costos, categoría y catálogo.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {string} tipo_precio Tipo de precio a consultar, por ejemplo "actual".
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de calculadora ZelerData.
 * @customfunction
 */
function ZELERDATA_CALCULADORA(cuenta, id_publicaciones, tipo_precio="actual", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CALCULADORA", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
/**
 * Devuelve retiros de Full dentro de un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de retiros.
 * @customfunction
 */
function ZELERDATA_RETIROS(cuenta, fecha_inicial, fecha_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_RETIROS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
/**
 * Devuelve URLs de imágenes por publicación o SKU.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {string} imagen Tipo de imagen a devolver, por ejemplo "principal".
 * @param {string} tipo_almacenamiento Filtro de almacenamiento; use "todos" para incluir todos.
 * @return {Object[][]} Filas con URLs de imágenes.
 * @customfunction
 */
function ZELERDATA_IMAGENES(cuenta, id_publicaciones="todos", skus="todos", imagen="principal", tipo_almacenamiento="todos") {
  return zelerdataExecute_("ZELERDATA_IMAGENES", cuenta, { id_publicaciones: id_publicaciones, skus: skus, imagen: imagen, tipo_almacenamiento: tipo_almacenamiento });
}
/**
 * Devuelve semanas con stock para publicaciones o SKUs en un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla semanal de presencia de stock.
 * @customfunction
 */
function ZELERDATA_SEMANASCONSTOCK(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, fecha_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_SEMANASCONSTOCK", cuenta, { id_publicaciones: id_publicaciones, skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
/**
 * Devuelve una tabla general de medidas por publicación o SKU.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de medidas generales.
 * @customfunction
 */
function ZELERDATA_MEDIDASGENERAL(cuenta, id_publicaciones="todos", skus="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_MEDIDASGENERAL", cuenta, { id_publicaciones: id_publicaciones, skus: skus, encabezados: encabezados });
}
/**
 * Devuelve medidas por publicación o SKU.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango; use "todos" para incluir todas.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs; use "todos" para incluir todos.
 * @return {Object[][]} Filas de medidas.
 * @customfunction
 */
function ZELERDATA_MEDIDAS(cuenta, id_publicaciones="todos", skus="todos") {
  return zelerdataExecute_("ZELERDATA_MEDIDAS", cuenta, { id_publicaciones: id_publicaciones, skus: skus });
}
/**
 * Devuelve la categoría por ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con categorías.
 * @customfunction
 */
function ZELERDATA_CATEGORIAS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_CATEGORIAS", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve si cada publicación pertenece a supermercado o formato regular.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con indicador de supermercado.
 * @customfunction
 */
function ZELERDATA_SUPERMERCADO(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_SUPERMERCADO", cuenta, { id_publicaciones: id_publicaciones });
}
/**
 * Devuelve información de catálogo disponible para la cuenta.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @return {Object[][]} Tabla de catálogo e imágenes.
 * @customfunction
 */
function ZELERDATA_OBTENER_CATALOGO(cuenta) {
  return zelerdataExecute_("ZELERDATA_OBTENER_CATALOGO", cuenta, {});
}
/**
 * Devuelve órdenes dentro de un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} estado Estado de orden a filtrar; use "todos" para incluir todos.
 * @param {string|number|Object[][]} compradores Comprador, lista o rango de compradores; vacío para no filtrar.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de órdenes.
 * @customfunction
 */
function ZELERDATA_ORDENES(cuenta, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ORDENES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
/**
 * Devuelve unidades vendidas por SKU e ID de publicación en un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @return {Object[][]} Filas con unidades vendidas.
 * @customfunction
 */
function ZELERDATA_UNIDADESVENDIDAS(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final) {
  return zelerdataExecute_("ZELERDATA_UNIDADESVENDIDAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, fecha_inicial: fecha_inicial, fecha_final: fecha_final });
}
/**
 * Devuelve órdenes filtradas por SKU y rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} estado Estado de orden a filtrar; use "todos" para incluir todos.
 * @param {string|number|Object[][]} compradores Comprador, lista o rango de compradores; vacío para no filtrar.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de órdenes por SKU.
 * @customfunction
 */
function ZELERDATA_ORDENESPORSKU(cuenta, skus, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ORDENESPORSKU", cuenta, { skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
/**
 * Devuelve días desde la última venta por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con días desde la última venta.
 * @customfunction
 */
function ZELERDATA_DIASDESDEULTIMAVENTA(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_DIASDESDEULTIMAVENTA", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
/**
 * Devuelve productos sin venta en el rango de días indicado.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {number|string} rango_dias Cantidad de días a evaluar.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de productos sin venta.
 * @customfunction
 */
function ZELERDATA_PRODUCTOSINVENTA(cuenta, rango_dias, encabezados="") {
  return zelerdataExecute_("ZELERDATA_PRODUCTOSINVENTA", cuenta, { rango_dias: rango_dias, encabezados: encabezados });
}
/**
 * Devuelve ventas por día para SKUs y publicaciones en el rango indicado.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {number|string} rango_dias Cantidad de días a evaluar.
 * @return {Object[][]} Filas con ventas por día.
 * @customfunction
 */
function ZELERDATA_VENTAPORDIAS(cuenta, skus, id_publicaciones, rango_dias) {
  return zelerdataExecute_("ZELERDATA_VENTAPORDIAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, rango_dias: rango_dias });
}
/**
 * Devuelve ventas recientes y stock actual por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de ventas y stock.
 * @customfunction
 */
function ZELERDATA_VENTASYSTOCK(cuenta, skus, id_publicaciones, encabezados="") {
  return zelerdataExecute_("ZELERDATA_VENTASYSTOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
/**
 * Devuelve el top de ventas por unidades en un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {number|string} cantidad_top Cantidad de posiciones del ranking.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de top ventas por unidades.
 * @customfunction
 */
function ZELERDATA_TOPVENTASUNIDADES(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return zelerdataExecute_("ZELERDATA_TOPVENTASUNIDADES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
/**
 * Devuelve el top de ventas por dinero en un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {number|string} cantidad_top Cantidad de posiciones del ranking.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de top ventas por dinero.
 * @customfunction
 */
function ZELERDATA_TOPVENTASDINERO(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return zelerdataExecute_("ZELERDATA_TOPVENTASDINERO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
/**
 * Devuelve costo de envío a cargo del vendedor por SKU e ID de publicación.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} skus SKU, lista o rango de SKUs.
 * @param {string|number|Object[][]} id_publicaciones ID de publicación, lista o rango.
 * @return {Object[][]} Filas con costo de envío del vendedor.
 * @customfunction
 */
function ZELERDATA_COSTOENVIOVENDEDOR(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_COSTOENVIOVENDEDOR", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
/**
 * Devuelve el importe total de ventas en un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} estado Estado de orden a filtrar; use "todos" para incluir todos.
 * @return {Object[][]} Valor total de ventas envuelto para Google Sheets.
 * @customfunction
 */
function ZELERDATA_VENTASTOTALES(cuenta, fecha_inicial, fecha_final, estado="todos") {
  return zelerdataExecute_("ZELERDATA_VENTASTOTALES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado });
}
/**
 * Devuelve compradores y datos de envío por ID de orden.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string|number|Object[][]} id_ordenes ID de orden, lista o rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de compradores.
 * @customfunction
 */
function ZELERDATA_COMPRADORES(cuenta, id_ordenes, encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMPRADORES", cuenta, { id_ordenes: id_ordenes, encabezados: encabezados });
}
/**
 * Devuelve envíos de Mercado Envíos según el estado de etiqueta.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {string} estado_etiqueta Estado de etiqueta a filtrar; use "todos" para incluir todos.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de envíos Mercado Envíos.
 * @customfunction
 */
function ZELERDATA_ENVIOSMERCADOENVIOS(cuenta, estado_etiqueta="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ENVIOSMERCADOENVIOS", cuenta, { estado_etiqueta: estado_etiqueta, encabezados: encabezados });
}
/**
 * Devuelve preguntas y respuestas dentro de fechas y horarios indicados.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicial Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string|number} horario_inicial Horario inicial del rango.
 * @param {string|number} horario_final Horario final del rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de preguntas y respuestas.
 * @customfunction
 */
function ZELERDATA_PREGUNTAS(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_PREGUNTAS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, horario_inicial: horario_inicial, horario_final: horario_final, encabezados: encabezados });
}
/**
 * Devuelve indicadores KPI de preguntas para un rango de fechas.
 * @param {string|number} cuenta Cuenta ZelerData o vendedor autorizado.
 * @param {Date|string|number} fecha_inicio Fecha inicial del rango.
 * @param {Date|string|number} fecha_final Fecha final del rango.
 * @param {string} encabezados Use "si" para incluir encabezados; vacío para omitirlos.
 * @return {Object[][]} Tabla de KPIs de preguntas.
 * @customfunction
 */
function ZELERDATA_PREGUNTASKPI(cuenta, fecha_inicio, fecha_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_PREGUNTASKPI", cuenta, { fecha_inicio: fecha_inicio, fecha_final: fecha_final, encabezados: encabezados });
}

function zelerdata_publicaciones(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", imagen="", encabezados="") {
  return ZELERDATA_PUBLICACIONES(cuenta, skus, tipo_almacenamiento, tipo_precio, imagen, encabezados);
}
function zelerdata_sku(cuenta, skus="todos") {
  return ZELERDATA_SKU(cuenta, skus);
}
function zelerdata_id(cuenta, skus="todos") {
  return ZELERDATA_ID(cuenta, skus);
}
function zelerdata_stock(cuenta, skus, id_publicaciones) {
  return ZELERDATA_STOCK(cuenta, skus, id_publicaciones);
}
function zelerdata_titulo(cuenta, id_publicaciones) {
  return ZELERDATA_TITULO(cuenta, id_publicaciones);
}
function zelerdata_url(cuenta, skus, id_publicaciones) {
  return ZELERDATA_URL(cuenta, skus, id_publicaciones);
}
function zelerdata_precio(cuenta, skus, id_publicaciones, tipo_precio="base") {
  return ZELERDATA_PRECIO(cuenta, skus, id_publicaciones, tipo_precio);
}
function zelerdata_idstock(cuenta, skus, encabezados="") {
  return ZELERDATA_IDSTOCK(cuenta, skus, encabezados);
}
function zelerdata_status(cuenta, id_publicaciones) {
  return ZELERDATA_STATUS(cuenta, id_publicaciones);
}
function zelerdata_pausadas(cuenta, id_publicaciones) {
  return ZELERDATA_PAUSADAS(cuenta, id_publicaciones);
}
function zelerdata_codigoml(cuenta, skus, id_publicaciones) {
  return ZELERDATA_CODIGOML(cuenta, skus, id_publicaciones);
}
function zelerdata_enviarafull(cuenta, codes) {
  return ZELERDATA_ENVIARAFULL(cuenta, codes);
}
function zelerdata_codigoml2skuid(cuenta, codigo_ml, encabezados="") {
  return ZELERDATA_CODIGOML2SKUID(cuenta, codigo_ml, encabezados);
}
function zelerdata_diaspublicada(cuenta, id_publicaciones) {
  return ZELERDATA_DIASPUBLICADA(cuenta, id_publicaciones);
}
function zelerdata_publicacionesdescuidadas(cuenta, tipo_precio="base", encabezados="") {
  return ZELERDATA_PUBLICACIONESDESCUIDADAS(cuenta, tipo_precio, encabezados);
}
function zelerdata_catalogo(cuenta, tipo_precio="base", encabezados="") {
  return ZELERDATA_CATALOGO(cuenta, tipo_precio, encabezados);
}
function zelerdata_dashboard(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return ZELERDATA_DASHBOARD(cuenta, skus, tipo_almacenamiento, tipo_precio, encabezados);
}
function zelerdata_tiemposinstock(cuenta, tipo_precio="base", encabezados="") {
  return ZELERDATA_TIEMPOSINSTOCK(cuenta, tipo_precio, encabezados);
}
function zelerdata_tiempoactiva(cuenta, id_publicaciones) {
  return ZELERDATA_TIEMPOACTIVA(cuenta, id_publicaciones);
}
function zelerdata_catalogosinvincular(cuenta, encabezados="") {
  return ZELERDATA_CATALOGOSINVINCULAR(cuenta, encabezados);
}
function zelerdata_catalogobuybox(cuenta, tipo_precio="base", encabezados="") {
  return ZELERDATA_CATALOGOBUYBOX(cuenta, tipo_precio, encabezados);
}
function zelerdata_comision(cuenta, id_publicaciones, encabezados="") {
  return ZELERDATA_COMISION(cuenta, id_publicaciones, encabezados);
}
function zelerdata_devoluciones(cuenta, fecha_inicio, fecha_final, id_publicaciones="todos", encabezados="") {
  return ZELERDATA_DEVOLUCIONES(cuenta, fecha_inicio, fecha_final, id_publicaciones, encabezados);
}
function zelerdata_competencia(cuenta, id_publicaciones="todos", encabezados="") {
  return ZELERDATA_COMPETENCIA(cuenta, id_publicaciones, encabezados);
}
function zelerdata_catalogotiempo(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return ZELERDATA_CATALOGOTIEMPO(cuenta, fecha_inicial, fecha_final, id_publicaciones, encabezados);
}
function zelerdata_preciohistorico(cuenta, id_publicaciones="todos", tipo_precio="base", encabezados="") {
  return ZELERDATA_PRECIOHISTORICO(cuenta, id_publicaciones, tipo_precio, encabezados);
}
function zelerdata_tiempostockactivo(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return ZELERDATA_TIEMPOSTOCKACTIVO(cuenta, fecha_inicial, fecha_final, id_publicaciones, encabezados);
}
function zelerdata_dashboardsincatalogo(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return ZELERDATA_DASHBOARDSINCATALOGO(cuenta, skus, tipo_almacenamiento, tipo_precio, encabezados);
}
function zelerdata_calidad(cuenta, encabezados="") {
  return ZELERDATA_CALIDAD(cuenta, encabezados);
}
function zelerdata_calculadora(cuenta, id_publicaciones, tipo_precio="actual", encabezados="") {
  return ZELERDATA_CALCULADORA(cuenta, id_publicaciones, tipo_precio, encabezados);
}
function zelerdata_retiros(cuenta, fecha_inicial, fecha_final, encabezados="") {
  return ZELERDATA_RETIROS(cuenta, fecha_inicial, fecha_final, encabezados);
}
function zelerdata_imagenes(cuenta, id_publicaciones="todos", skus="todos", imagen="principal", tipo_almacenamiento="todos") {
  return ZELERDATA_IMAGENES(cuenta, id_publicaciones, skus, imagen, tipo_almacenamiento);
}
function zelerdata_semanasconstock(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, fecha_final, encabezados="") {
  return ZELERDATA_SEMANASCONSTOCK(cuenta, id_publicaciones, skus, fecha_inicial, fecha_final, encabezados);
}
function zelerdata_medidasgeneral(cuenta, id_publicaciones="todos", skus="todos", encabezados="") {
  return ZELERDATA_MEDIDASGENERAL(cuenta, id_publicaciones, skus, encabezados);
}
function zelerdata_medidas(cuenta, id_publicaciones="todos", skus="todos") {
  return ZELERDATA_MEDIDAS(cuenta, id_publicaciones, skus);
}
function zelerdata_categorias(cuenta, id_publicaciones) {
  return ZELERDATA_CATEGORIAS(cuenta, id_publicaciones);
}
function zelerdata_supermercado(cuenta, id_publicaciones) {
  return ZELERDATA_SUPERMERCADO(cuenta, id_publicaciones);
}
function zelerdata_obtener_catalogo(cuenta) {
  return ZELERDATA_OBTENER_CATALOGO(cuenta);
}
function zelerdata_ordenes(cuenta, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return ZELERDATA_ORDENES(cuenta, fecha_inicial, fecha_final, estado, compradores, encabezados);
}
function zelerdata_unidadesvendidas(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final) {
  return ZELERDATA_UNIDADESVENDIDAS(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final);
}
function zelerdata_ordenesporsku(cuenta, skus, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return ZELERDATA_ORDENESPORSKU(cuenta, skus, fecha_inicial, fecha_final, estado, compradores, encabezados);
}
function zelerdata_diasdesdeultimaventa(cuenta, skus, id_publicaciones) {
  return ZELERDATA_DIASDESDEULTIMAVENTA(cuenta, skus, id_publicaciones);
}
function zelerdata_productosinventa(cuenta, rango_dias, encabezados="") {
  return ZELERDATA_PRODUCTOSINVENTA(cuenta, rango_dias, encabezados);
}
function zelerdata_ventapordias(cuenta, skus, id_publicaciones, rango_dias) {
  return ZELERDATA_VENTAPORDIAS(cuenta, skus, id_publicaciones, rango_dias);
}
function zelerdata_ventasystock(cuenta, skus, id_publicaciones, encabezados="") {
  return ZELERDATA_VENTASYSTOCK(cuenta, skus, id_publicaciones, encabezados);
}
function zelerdata_topventasunidades(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return ZELERDATA_TOPVENTASUNIDADES(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados);
}
function zelerdata_topventasdinero(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return ZELERDATA_TOPVENTASDINERO(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados);
}
function zelerdata_costoenviovendedor(cuenta, skus, id_publicaciones) {
  return ZELERDATA_COSTOENVIOVENDEDOR(cuenta, skus, id_publicaciones);
}
function zelerdata_ventastotales(cuenta, fecha_inicial, fecha_final, estado="todos") {
  return ZELERDATA_VENTASTOTALES(cuenta, fecha_inicial, fecha_final, estado);
}
function zelerdata_compradores(cuenta, id_ordenes, encabezados="") {
  return ZELERDATA_COMPRADORES(cuenta, id_ordenes, encabezados);
}
function zelerdata_enviosmercadoenvios(cuenta, estado_etiqueta="todos", encabezados="") {
  return ZELERDATA_ENVIOSMERCADOENVIOS(cuenta, estado_etiqueta, encabezados);
}
function zelerdata_preguntas(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados="") {
  return ZELERDATA_PREGUNTAS(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados);
}
function zelerdata_preguntaskpi(cuenta, fecha_inicio, fecha_final, encabezados="") {
  return ZELERDATA_PREGUNTASKPI(cuenta, fecha_inicio, fecha_final, encabezados);
}
