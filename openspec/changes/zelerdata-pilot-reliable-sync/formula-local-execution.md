# Local formula execution evidence

This is local dispatcher execution, not deployed pilot or Google Sheets evidence.
All 52 registered formulas were invoked in passing existing handler tests. The
fixtures include doubles; neither a returned result nor expected unavailability
certifies positive data, real Mongo query semantics, freshness, or Sheets output.
Each row names one reproducible test; the JSON artifact contains all observed
test/formula/outcome pairs. Counts are distinct passing-test/outcome observations,
not assertions or independent production cases. Positive/absent/filter/range
acceptance still requires individual assertion review and runtime evidence.

Reproduce from repository root:

```sh
uv run pytest -q modules/sheets/tests/test_formula_execution_evidence.py \
  modules/sheets/tests/test_formula_handlers*.py \
  modules/sheets/tests/test_formula_read_models.py \
  modules/sheets/tests/test_formula_recovery.py \
  -p modules.sheets.tests.formula_execution_evidence \
  --formula-evidence=/tmp/formula-local-matrix.json
```

The selected tests use local fixtures/doubles. Before broader Mongo suites, set
an explicit verified disposable loopback database; never inherit production URI.
The opt-in plugin stores only names and outcomes, not arguments or cell values.
Failed/skipped tests do not provide evidence. No change is made to the deployed
Observed/Evidence columns of `formula-matrix.md`; task 4.1 remains open.

| Formula | Returned | Expected unavailable | Example passing test |
| --- | ---: | ---: | --- |
| `ZELERDATA_CALCULADORA` | 75 | 11 | `modules/sheets/tests/test_formula_handlers_quality_calculator.py::test_calculator_requests_targeted_recovery_for_present_unavailable_fields[seller_shipping_cost-False]` |
| `ZELERDATA_CALIDAD` | 17 | 2 | `modules/sheets/tests/test_formula_handlers_quality_calculator.py::test_calidad_uses_modern_local_quality_projection_without_suggested_price` |
| `ZELERDATA_CATALOGO` | 16 | 4 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_catalog_sales_require_each_window_without_hiding_item_data[0]` |
| `ZELERDATA_CATALOGOBUYBOX` | 21 | 2 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_catalog_outputs_include_every_stored_snapshot[ZELERDATA_CATALOGOBUYBOX-catalog_buybox_snapshots]` |
| `ZELERDATA_CATALOGOSINVINCULAR` | 2 | 1 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_item_catalog_handlers_use_local_rows_and_catalog_snapshots` |
| `ZELERDATA_CATALOGOTIEMPO` | 2 | 3 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_CATALOGOTIEMPO-catalog_time_metrics]` |
| `ZELERDATA_CATALOGO_COMPLETO` | 13 | 1 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_catalog_outputs_include_every_stored_snapshot[ZELERDATA_CATALOGO_COMPLETO-catalog_product_snapshots]` |
| `ZELERDATA_CATEGORIAS` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_categorias_returns_category_by_item_id_with_blanks_for_misses` |
| `ZELERDATA_CODIGOML` | 4 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_url_and_codigo_ml_handlers_lookup_sku_item_pairs_with_blanks_for_misses` |
| `ZELERDATA_CODIGOML2SKUID` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_codigo_ml_to_sku_id_returns_seller_scoped_table_with_optional_headers` |
| `ZELERDATA_COMISION` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_comision_returns_source_backed_projection_table_with_headers_and_na` |
| `ZELERDATA_COMPRADORES` | 8 | 3 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_formula_api_wires_batch_b_handlers_and_keeps_other_batch_b_data_unavailable` |
| `ZELERDATA_COSTOENVIOVENDEDOR` | 2 | 5 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_shipping_includes_latest_order_after_5000_older_orders[ZELERDATA_COSTOENVIOVENDEDOR]` |
| `ZELERDATA_DASHBOARD` | 27 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_publicaciones_dashboard_emit_na_for_deferred_fields_and_current_shipping` |
| `ZELERDATA_DASHBOARDSINCATALOGO` | 10 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_dashboard_formulas_omit_cart_id_columns_and_keep_sales_windows_aligned[ZELERDATA_DASHBOARDSINCATALOGO]` |
| `ZELERDATA_DEVOLUCIONES` | 5 | 22 | `modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py::test_devoluciones_groups_return_claims_by_item_and_sku` |
| `ZELERDATA_DIASDESDEULTIMAVENTA` | 4 | 0 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_dias_desde_ultima_venta_uses_last_seller_scoped_order_date` |
| `ZELERDATA_DIASPUBLICADA` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_title_status_and_days_handlers_lookup_item_ids_with_blanks_for_misses` |
| `ZELERDATA_ENVIOSMERCADOENVIOS` | 13 | 2 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_shipping_includes_latest_order_after_5000_older_orders[ZELERDATA_ENVIOSMERCADOENVIOS]` |
| `ZELERDATA_ID` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_sku_and_id_handlers_use_seller_scoped_sku_index_and_preserve_range_order` |
| `ZELERDATA_IDSTOCK` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_idstock_returns_seller_scoped_table_with_optional_headers` |
| `ZELERDATA_IMAGENES` | 2 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_item_formula_handlers_return_blanks_without_enriched_source_fields` |
| `ZELERDATA_MEDIDAS` | 2 | 1 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_item_catalog_handlers_use_local_rows_and_catalog_snapshots` |
| `ZELERDATA_MEDIDASGENERAL` | 2 | 1 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_item_catalog_handlers_use_local_rows_and_catalog_snapshots` |
| `ZELERDATA_OBTENER_CATALOGO` | 13 | 2 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_catalog_outputs_include_every_stored_snapshot[ZELERDATA_OBTENER_CATALOGO-catalog_product_snapshots]` |
| `ZELERDATA_ORDENES` | 33 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_ordenes_returns_order_table_with_status_buyer_filters_and_headers` |
| `ZELERDATA_ORDENESPORSKU` | 15 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_ordenes_keeps_unresolved_sku_lines_and_sku_filter_omits_them` |
| `ZELERDATA_PAUSADAS` | 3 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_pause_duration_formulas_share_effective_observed_pause_basis` |
| `ZELERDATA_PRECIO` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_stock_and_precio_handlers_lookup_scalar_and_range_pairs_with_blanks_for_misses` |
| `ZELERDATA_PRECIOHISTORICO` | 2 | 2 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_PRECIOHISTORICO-price_history_snapshots]` |
| `ZELERDATA_PREGUNTAS` | 3 | 3 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_preguntas_blocks_productive_output_until_questions_read_model_is_fresh` |
| `ZELERDATA_PREGUNTASKPI` | 2 | 2 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_preguntas_kpi_blocks_stale_questions_freshness_marker` |
| `ZELERDATA_PRODUCTOSINVENTA` | 3 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_productos_sin_venta_uses_shipping_payer_and_na_for_deferred_change_date` |
| `ZELERDATA_PUBLICACIONES` | 8 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_publicaciones_dashboard_emit_na_for_deferred_fields_and_current_shipping` |
| `ZELERDATA_PUBLICACIONESDESCUIDADAS` | 3 | 2 | `modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py::test_publicaciones_descuidadas_uses_current_full_out_of_stock_paused_rows` |
| `ZELERDATA_RETIROS` | 2 | 3 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_RETIROS-full_withdrawals]` |
| `ZELERDATA_SEMANASCONSTOCK` | 2 | 3 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_SEMANASCONSTOCK-stock_time_metrics]` |
| `ZELERDATA_SKU` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_sku_and_id_handlers_use_seller_scoped_sku_index_and_preserve_range_order` |
| `ZELERDATA_STATUS` | 1 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_title_status_and_days_handlers_lookup_item_ids_with_blanks_for_misses` |
| `ZELERDATA_STOCK` | 2 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_stock_and_precio_handlers_lookup_scalar_and_range_pairs_with_blanks_for_misses` |
| `ZELERDATA_SUPERMERCADO` | 2 | 2 | `modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py::test_item_catalog_handlers_use_local_rows_and_catalog_snapshots` |
| `ZELERDATA_TIEMPOACTIVA` | 1 | 2 | `modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py::test_tiempoactiva_uses_item_status_state_history_not_current_row_guessing` |
| `ZELERDATA_TIEMPOSINSTOCK` | 2 | 2 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_TIEMPOSINSTOCK-stockout_snapshots]` |
| `ZELERDATA_TIEMPOSTOCKACTIVO` | 2 | 4 | `modules/sheets/tests/test_formula_handlers_remaining_phase4.py::test_history_formulas_do_not_truncate_complete_read_models[ZELERDATA_TIEMPOSTOCKACTIVO-stock_time_metrics]` |
| `ZELERDATA_TITULO` | 2 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_title_status_and_days_handlers_lookup_item_ids_with_blanks_for_misses` |
| `ZELERDATA_TOPVENTASDINERO` | 1 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_top_ventas_unidades_and_dinero_rank_enriched_items_deterministically` |
| `ZELERDATA_TOPVENTASUNIDADES` | 1 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_top_ventas_unidades_and_dinero_rank_enriched_items_deterministically` |
| `ZELERDATA_UNIDADESVENDIDAS` | 6 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_unidades_vendidas_ignores_unresolved_sku_order_lines` |
| `ZELERDATA_URL` | 2 | 0 | `modules/sheets/tests/test_formula_handlers_core.py::test_url_and_codigo_ml_handlers_lookup_sku_item_pairs_with_blanks_for_misses` |
| `ZELERDATA_VENTAPORDIAS` | 1 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_venta_por_dias_sums_recent_units_from_now_with_sku_enrichment` |
| `ZELERDATA_VENTASTOTALES` | 7 | 3 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_ventas_totales_uses_seller_scoped_orders_date_range_and_status_filters` |
| `ZELERDATA_VENTASYSTOCK` | 1 | 1 | `modules/sheets/tests/test_formula_handlers_orders_questions.py::test_ventas_y_stock_combines_recent_sales_windows_with_current_stock` |
