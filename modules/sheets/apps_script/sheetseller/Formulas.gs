// databaseName is a legacy name; pass the seller nickname for the platform token scope.
// collectionName is a legacy name; pass the seller nickname for the platform token scope.
function SHEETSELLER_PUBLICACIONES(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", imagen="", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PUBLICACIONES", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, imagen: imagen, encabezados: encabezados });
}
function SHEETSELLER_SKU(cuenta, skus="todos") {
  return sheetsellerExecute_("SHEETSELLER_SKU", cuenta, { skus: skus });
}
function SHEETSELLER_ID(cuenta, skus="todos") {
  return sheetsellerExecute_("SHEETSELLER_ID", cuenta, { skus: skus });
}
function SHEETSELLER_STOCK(cuenta, skus, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_STOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function SHEETSELLER_TITULO(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_TITULO", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_URL(cuenta, skus, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_URL", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function SHEETSELLER_PRECIO(cuenta, skus, id_publicaciones, tipo_precio="base") {
  return sheetsellerExecute_("SHEETSELLER_PRECIO", cuenta, { skus: skus, id_publicaciones: id_publicaciones, tipo_precio: tipo_precio });
}
function SHEETSELLER_IDSTOCK(cuenta, skus, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_IDSTOCK", cuenta, { skus: skus, encabezados: encabezados });
}
function SHEETSELLER_STATUS(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_STATUS", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_PAUSADAS(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_PAUSADAS", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_CODIGOML(cuenta, skus, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_CODIGOML", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function sheetseller_enviarafull(databaseName, codes) {
  return sheetsellerExecute_("sheetseller_enviarafull", databaseName, { codes: codes });
}
function SHEETSELLER_CODIGOML2SKUID(cuenta, codigo_ml, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CODIGOML2SKUID", cuenta, { codigo_ml: codigo_ml, encabezados: encabezados });
}
function SHEETSELLER_DIASPUBLICADA(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_DIASPUBLICADA", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_PUBLICACIONESDESCUIDADAS(cuenta, tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PUBLICACIONESDESCUIDADAS", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_CATALOGO(cuenta, tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CATALOGO", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_DASHBOARD(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_DASHBOARD", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_TIEMPOSINSTOCK(cuenta, tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_TIEMPOSINSTOCK", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_TIEMPOACTIVA(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_TIEMPOACTIVA", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_CATALOGOSINVINCULAR(cuenta, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CATALOGOSINVINCULAR", cuenta, { encabezados: encabezados });
}
function SHEETSELLER_CATALOGOBUYBOX(cuenta, tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CATALOGOBUYBOX", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_COMISION(cuenta, id_publicaciones, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_COMISION", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_DEVOLUCIONES(cuenta, fecha_inicio, fecha_final, id_publicaciones="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_DEVOLUCIONES", cuenta, { fecha_inicio: fecha_inicio, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_COMPETENCIA(cuenta, id_publicaciones="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_COMPETENCIA", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_CATALOGOTIEMPO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CATALOGOTIEMPO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_PRECIOHISTORICO(cuenta, id_publicaciones="todos", tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PRECIOHISTORICO", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_TIEMPOSTOCKACTIVO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_TIEMPOSTOCKACTIVO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_DASHBOARDSINCATALOGO(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_DASHBOARDSINCATALOGO", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_CALIDAD(cuenta, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CALIDAD", cuenta, { encabezados: encabezados });
}
function SHEETSELLER_CALCULADORA(cuenta, id_publicaciones, tipo_precio="actual", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_CALCULADORA", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
function SHEETSELLER_RETIROS(cuenta, fecha_inicial, fecha_final, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_RETIROS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
function SHEETSELLER_IMAGENES(cuenta, id_publicaciones="todos", skus="todos", imagen="principal", tipo_almacenamiento="todos") {
  return sheetsellerExecute_("SHEETSELLER_IMAGENES", cuenta, { id_publicaciones: id_publicaciones, skus: skus, imagen: imagen, tipo_almacenamiento: tipo_almacenamiento });
}
function SHEETSELLER_SEMANASCONSTOCK(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, fecha_final, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_SEMANASCONSTOCK", cuenta, { id_publicaciones: id_publicaciones, skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
function SHEETSELLER_MEDIDASGENERAL(cuenta, id_publicaciones="todos", skus="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_MEDIDASGENERAL", cuenta, { id_publicaciones: id_publicaciones, skus: skus, encabezados: encabezados });
}
function SHEETSELLER_MEDIDAS(cuenta, id_publicaciones="todos", skus="todos") {
  return sheetsellerExecute_("SHEETSELLER_MEDIDAS", cuenta, { id_publicaciones: id_publicaciones, skus: skus });
}
function SHEETSELLER_CATEGORIAS(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_CATEGORIAS", cuenta, { id_publicaciones: id_publicaciones });
}
function SHEETSELLER_SUPERMERCADO(cuenta, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_SUPERMERCADO", cuenta, { id_publicaciones: id_publicaciones });
}
function sheetseller_obtener_catalogo(collectionName) {
  return sheetsellerExecute_("sheetseller_obtener_catalogo", collectionName, {});
}
function SHEETSELLER_ORDENES(cuenta, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_ORDENES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
function SHEETSELLER_UNIDADESVENDIDAS(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final) {
  return sheetsellerExecute_("SHEETSELLER_UNIDADESVENDIDAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, fecha_inicial: fecha_inicial, fecha_final: fecha_final });
}
function SHEETSELLER_ORDENESPORSKU(cuenta, skus, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_ORDENESPORSKU", cuenta, { skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
function SHEETSELLER_DIASDESDEULTIMAVENTA(cuenta, skus, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_DIASDESDEULTIMAVENTA", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function SHEETSELLER_PRODUCTOSINVENTA(cuenta, rango_dias, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PRODUCTOSINVENTA", cuenta, { rango_dias: rango_dias, encabezados: encabezados });
}
function SHEETSELLER_VENTAPORDIAS(cuenta, skus, id_publicaciones, rango_dias) {
  return sheetsellerExecute_("SHEETSELLER_VENTAPORDIAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, rango_dias: rango_dias });
}
function SHEETSELLER_VENTASYSTOCK(cuenta, skus, id_publicaciones, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_VENTASYSTOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function SHEETSELLER_TOPVENTASUNIDADES(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_TOPVENTASUNIDADES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
function SHEETSELLER_TOPVENTASDINERO(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_TOPVENTASDINERO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
function SHEETSELLER_COSTOENVIOVENDEDOR(cuenta, skus, id_publicaciones) {
  return sheetsellerExecute_("SHEETSELLER_COSTOENVIOVENDEDOR", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function SHEETSELLER_VENTASTOTALES(cuenta, fecha_inicial, fecha_final, estado="todos") {
  return sheetsellerExecute_("SHEETSELLER_VENTASTOTALES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado });
}
function SHEETSELLER_COMPRADORES(cuenta, id_ordenes, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_COMPRADORES", cuenta, { id_ordenes: id_ordenes, encabezados: encabezados });
}
function SHEETSELLER_ENVIOSMERCADOENVIOS(cuenta, estado_etiqueta="todos", encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_ENVIOSMERCADOENVIOS", cuenta, { estado_etiqueta: estado_etiqueta, encabezados: encabezados });
}
function SHEETSELLER_PREGUNTAS(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PREGUNTAS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, horario_inicial: horario_inicial, horario_final: horario_final, encabezados: encabezados });
}
function SHEETSELLER_PREGUNTASKPI(cuenta, fecha_inicio, fecha_final, encabezados="") {
  return sheetsellerExecute_("SHEETSELLER_PREGUNTASKPI", cuenta, { fecha_inicio: fecha_inicio, fecha_final: fecha_final, encabezados: encabezados });
}
