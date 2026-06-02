function ZELERDATA_PUBLICACIONES(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", imagen="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PUBLICACIONES", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, imagen: imagen, encabezados: encabezados });
}
function ZELERDATA_SKU(cuenta, skus="todos") {
  return zelerdataExecute_("ZELERDATA_SKU", cuenta, { skus: skus });
}
function ZELERDATA_ID(cuenta, skus="todos") {
  return zelerdataExecute_("ZELERDATA_ID", cuenta, { skus: skus });
}
function ZELERDATA_STOCK(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_STOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function ZELERDATA_TITULO(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_TITULO", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_URL(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_URL", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function ZELERDATA_PRECIO(cuenta, skus, id_publicaciones, tipo_precio="base") {
  return zelerdataExecute_("ZELERDATA_PRECIO", cuenta, { skus: skus, id_publicaciones: id_publicaciones, tipo_precio: tipo_precio });
}
function ZELERDATA_IDSTOCK(cuenta, skus, encabezados="") {
  return zelerdataExecute_("ZELERDATA_IDSTOCK", cuenta, { skus: skus, encabezados: encabezados });
}
function ZELERDATA_STATUS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_STATUS", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_PAUSADAS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_PAUSADAS", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_CODIGOML(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_CODIGOML", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function ZELERDATA_ENVIARAFULL(cuenta, codes) {
  return zelerdataExecute_("ZELERDATA_ENVIARAFULL", cuenta, { codes: codes });
}
function ZELERDATA_CODIGOML2SKUID(cuenta, codigo_ml, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CODIGOML2SKUID", cuenta, { codigo_ml: codigo_ml, encabezados: encabezados });
}
function ZELERDATA_DIASPUBLICADA(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_DIASPUBLICADA", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_PUBLICACIONESDESCUIDADAS(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PUBLICACIONESDESCUIDADAS", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_CATALOGO(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGO", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_DASHBOARD(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DASHBOARD", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_TIEMPOSINSTOCK(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_TIEMPOSINSTOCK", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_TIEMPOACTIVA(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_TIEMPOACTIVA", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_CATALOGOSINVINCULAR(cuenta, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOSINVINCULAR", cuenta, { encabezados: encabezados });
}
function ZELERDATA_CATALOGOBUYBOX(cuenta, tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOBUYBOX", cuenta, { tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_COMISION(cuenta, id_publicaciones, encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMISION", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_DEVOLUCIONES(cuenta, fecha_inicio, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DEVOLUCIONES", cuenta, { fecha_inicio: fecha_inicio, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_COMPETENCIA(cuenta, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMPETENCIA", cuenta, { id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_CATALOGOTIEMPO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CATALOGOTIEMPO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_PRECIOHISTORICO(cuenta, id_publicaciones="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_PRECIOHISTORICO", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_TIEMPOSTOCKACTIVO(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_TIEMPOSTOCKACTIVO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_DASHBOARDSINCATALOGO(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="") {
  return zelerdataExecute_("ZELERDATA_DASHBOARDSINCATALOGO", cuenta, { skus: skus, tipo_almacenamiento: tipo_almacenamiento, tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_CALIDAD(cuenta, encabezados="") {
  return zelerdataExecute_("ZELERDATA_CALIDAD", cuenta, { encabezados: encabezados });
}
function ZELERDATA_CALCULADORA(cuenta, id_publicaciones, tipo_precio="actual", encabezados="") {
  return zelerdataExecute_("ZELERDATA_CALCULADORA", cuenta, { id_publicaciones: id_publicaciones, tipo_precio: tipo_precio, encabezados: encabezados });
}
function ZELERDATA_RETIROS(cuenta, fecha_inicial, fecha_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_RETIROS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
function ZELERDATA_IMAGENES(cuenta, id_publicaciones="todos", skus="todos", imagen="principal", tipo_almacenamiento="todos") {
  return zelerdataExecute_("ZELERDATA_IMAGENES", cuenta, { id_publicaciones: id_publicaciones, skus: skus, imagen: imagen, tipo_almacenamiento: tipo_almacenamiento });
}
function ZELERDATA_SEMANASCONSTOCK(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, fecha_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_SEMANASCONSTOCK", cuenta, { id_publicaciones: id_publicaciones, skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, encabezados: encabezados });
}
function ZELERDATA_MEDIDASGENERAL(cuenta, id_publicaciones="todos", skus="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_MEDIDASGENERAL", cuenta, { id_publicaciones: id_publicaciones, skus: skus, encabezados: encabezados });
}
function ZELERDATA_MEDIDAS(cuenta, id_publicaciones="todos", skus="todos") {
  return zelerdataExecute_("ZELERDATA_MEDIDAS", cuenta, { id_publicaciones: id_publicaciones, skus: skus });
}
function ZELERDATA_CATEGORIAS(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_CATEGORIAS", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_SUPERMERCADO(cuenta, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_SUPERMERCADO", cuenta, { id_publicaciones: id_publicaciones });
}
function ZELERDATA_OBTENER_CATALOGO(cuenta) {
  return zelerdataExecute_("ZELERDATA_OBTENER_CATALOGO", cuenta, {});
}
function ZELERDATA_ORDENES(cuenta, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ORDENES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
function ZELERDATA_UNIDADESVENDIDAS(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final) {
  return zelerdataExecute_("ZELERDATA_UNIDADESVENDIDAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, fecha_inicial: fecha_inicial, fecha_final: fecha_final });
}
function ZELERDATA_ORDENESPORSKU(cuenta, skus, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ORDENESPORSKU", cuenta, { skus: skus, fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado, compradores: compradores, encabezados: encabezados });
}
function ZELERDATA_DIASDESDEULTIMAVENTA(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_DIASDESDEULTIMAVENTA", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function ZELERDATA_PRODUCTOSINVENTA(cuenta, rango_dias, encabezados="") {
  return zelerdataExecute_("ZELERDATA_PRODUCTOSINVENTA", cuenta, { rango_dias: rango_dias, encabezados: encabezados });
}
function ZELERDATA_VENTAPORDIAS(cuenta, skus, id_publicaciones, rango_dias) {
  return zelerdataExecute_("ZELERDATA_VENTAPORDIAS", cuenta, { skus: skus, id_publicaciones: id_publicaciones, rango_dias: rango_dias });
}
function ZELERDATA_VENTASYSTOCK(cuenta, skus, id_publicaciones, encabezados="") {
  return zelerdataExecute_("ZELERDATA_VENTASYSTOCK", cuenta, { skus: skus, id_publicaciones: id_publicaciones, encabezados: encabezados });
}
function ZELERDATA_TOPVENTASUNIDADES(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return zelerdataExecute_("ZELERDATA_TOPVENTASUNIDADES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
function ZELERDATA_TOPVENTASDINERO(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="") {
  return zelerdataExecute_("ZELERDATA_TOPVENTASDINERO", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, cantidad_top: cantidad_top, encabezados: encabezados });
}
function ZELERDATA_COSTOENVIOVENDEDOR(cuenta, skus, id_publicaciones) {
  return zelerdataExecute_("ZELERDATA_COSTOENVIOVENDEDOR", cuenta, { skus: skus, id_publicaciones: id_publicaciones });
}
function ZELERDATA_VENTASTOTALES(cuenta, fecha_inicial, fecha_final, estado="todos") {
  return zelerdataExecute_("ZELERDATA_VENTASTOTALES", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, estado: estado });
}
function ZELERDATA_COMPRADORES(cuenta, id_ordenes, encabezados="") {
  return zelerdataExecute_("ZELERDATA_COMPRADORES", cuenta, { id_ordenes: id_ordenes, encabezados: encabezados });
}
function ZELERDATA_ENVIOSMERCADOENVIOS(cuenta, estado_etiqueta="todos", encabezados="") {
  return zelerdataExecute_("ZELERDATA_ENVIOSMERCADOENVIOS", cuenta, { estado_etiqueta: estado_etiqueta, encabezados: encabezados });
}
function ZELERDATA_PREGUNTAS(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados="") {
  return zelerdataExecute_("ZELERDATA_PREGUNTAS", cuenta, { fecha_inicial: fecha_inicial, fecha_final: fecha_final, horario_inicial: horario_inicial, horario_final: horario_final, encabezados: encabezados });
}
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
