from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from xml.etree import ElementTree as ET


class LegacyBatchContractError(ValueError):
    """Raised when the ZIP/Excel envelope cannot be accepted as a legacy batch."""


REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "SKU",
    "CodigoBarras",
    "Precio",
    "TipoLogistica",
    "TipoPublicacion",
    "EnvioGratis",
)
ACCEPTED_LOGISTICS: Final[set[str]] = {
    "default",
    "drop off",
    "fulfillment",
    "pick up",
    "cross docking",
    "xd drop off",
    "self service",
    "turbo",
    "custom",
    "no especificado",
    "drop_shipping",
    "cross_docking",
    "flex",
}
ACCEPTED_LISTING_TYPES: Final[set[str]] = {
    "premium",
    "clasica",
    "clásica",
    "oro premium",
    "oro",
    "plata",
    "bronce",
    "gratuita",
}
ACCEPTED_FREE_SHIPPING: Final[set[str]] = {"si", "no"}
IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (".jpg", ".jpeg", ".png", ".webp")
IMAGE_CONTENT_TYPES: Final[dict[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class ParsedBatchImage:
    filename: str
    content_type: str
    width: int
    height: int
    hash: str
    data: bytes


@dataclass(frozen=True)
class ParsedBatchRow:
    row_number: int
    sku: str
    codigo_barras: str
    price: float
    logistics_type: str
    listing_type: str
    free_shipping: bool
    publicar: str
    raw: dict[str, str]
    images: list[ParsedBatchImage]
    errors: list[str]


@dataclass(frozen=True)
class ParsedLegacyBatch:
    account_id: str
    rows: list[ParsedBatchRow]
    global_warnings: list[str]


def parse_legacy_batch_zip(content: bytes) -> ParsedLegacyBatch:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise LegacyBatchContractError("El archivo ZIP no es válido") from exc

    with archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        excel_name, root_prefix = _locate_excel(names)
        account_id, excel_rows = _read_xlsx_rows(archive.read(excel_name))
        image_map, image_warnings = _read_images(archive, names=names, root_prefix=root_prefix)
        excel_skus = {str(row.get("SKU", "")).strip() for row in excel_rows}
        warnings = [
            f"SKU folder {sku} is not present in Excel rows"
            for sku in sorted(set(image_map) - excel_skus)
        ]
        warnings.extend(image_warnings)
        return ParsedLegacyBatch(
            account_id=account_id,
            rows=[
                _parse_row(index, row, image_map) for index, row in enumerate(excel_rows, start=3)
            ],
            global_warnings=warnings,
        )


def _locate_excel(names: list[str]) -> tuple[str, str]:
    for name in names:
        if "/" not in name and name.lower().endswith((".xlsx", ".xls")):
            return name, ""
    first_folders = sorted({name.split("/", 1)[0] for name in names if "/" in name})
    for folder in first_folders:
        prefix = f"{folder}/"
        for name in names:
            if (
                name.startswith(prefix)
                and name.count("/") == 1
                and name.lower().endswith((".xlsx", ".xls"))
            ):
                return name, prefix
    raise LegacyBatchContractError(
        "No se encontró ningún archivo Excel en la estructura esperada del ZIP"
    )


def _read_xlsx_rows(content: bytes) -> tuple[str, list[dict[str, str]]]:
    try:
        workbook = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise LegacyBatchContractError("El archivo Excel no es un .xlsx válido") from exc
    with workbook:
        sheet_name = _first_sheet_name(workbook)
        sheet_xml = workbook.read(sheet_name)
        shared_strings = _shared_strings(workbook)
    rows = _sheet_rows(sheet_xml, shared_strings=shared_strings)
    if len(rows) < 2 or len(rows[0]) < 2:
        raise LegacyBatchContractError(
            "El archivo Excel no tiene el formato esperado para la cuenta en la celda B1."
        )
    if rows[0][0].strip() != "Cuenta Mercado Libre:":
        raise LegacyBatchContractError("La celda A1 debe contener el texto 'Cuenta Mercado Libre:'")
    account_id = rows[0][1].strip()
    if not account_id:
        raise LegacyBatchContractError(
            "El nombre de la cuenta en la celda B1 del Excel no puede estar vacío."
        )
    headers = [value.strip() for value in rows[1]]
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing_columns:
        raise LegacyBatchContractError(
            f"Faltan columnas requeridas en el Excel: {', '.join(missing_columns)}"
        )
    return account_id, [
        {
            header: row[index].strip() if index < len(row) else ""
            for index, header in enumerate(headers)
        }
        for row in rows[2:]
        if any(value.strip() for value in row)
    ]


def _first_sheet_name(workbook: zipfile.ZipFile) -> str:
    candidates = sorted(
        name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet")
    )
    if not candidates:
        raise LegacyBatchContractError("El archivo Excel no contiene hojas de productos")
    return candidates[0]


def _shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))  # noqa: S314
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    return ["".join(text.itertext()) for text in root.findall(f"{namespace}si")]


def _sheet_rows(sheet_xml: bytes, *, shared_strings: list[str]) -> list[list[str]]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    root = ET.fromstring(sheet_xml)  # noqa: S314
    result: list[list[str]] = []
    for row in root.findall(f".//{namespace}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{namespace}c"):
            reference = str(cell.attrib.get("r", "A1"))
            col_index = _column_index("".join(char for char in reference if char.isalpha()))
            values[col_index] = _cell_value(
                cell, shared_strings=shared_strings, namespace=namespace
            )
        width = max(values, default=0)
        result.append([values.get(index, "") for index in range(1, width + 1)])
    return result


def _cell_value(cell: ET.Element, *, shared_strings: list[str], namespace: str) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{namespace}is")
        return "" if inline is None else "".join(inline.itertext())
    raw = cell.find(f"{namespace}v")
    if raw is None or raw.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(raw.text)]
    return raw.text


def _column_index(column: str) -> int:
    result = 0
    for char in column:
        result = result * 26 + ord(char.upper()) - ord("A") + 1
    return result


def _read_images(
    archive: zipfile.ZipFile, *, names: list[str], root_prefix: str
) -> tuple[dict[str, list[ParsedBatchImage]], list[str]]:
    image_map: dict[str, list[ParsedBatchImage]] = {}
    warnings: list[str] = []
    for name in names:
        lower = name.lower()
        extension = next((ext for ext in IMAGE_EXTENSIONS if lower.endswith(ext)), None)
        if extension is None:
            continue
        relative = (
            name.removeprefix(root_prefix) if root_prefix and name.startswith(root_prefix) else name
        )
        parts = relative.split("/")
        if len(parts) < 2 or not parts[0]:
            continue
        data = archive.read(name)
        width, height = _image_dimensions(data, extension=extension)
        if width == 0 or height == 0:
            warnings.append(f"{parts[-1]} dimensions could not be read")
        image_map.setdefault(parts[0], []).append(
            ParsedBatchImage(
                filename=parts[-1],
                content_type=IMAGE_CONTENT_TYPES[extension],
                width=width,
                height=height,
                hash=sha256(data).hexdigest(),
                data=data,
            )
        )
    return image_map, warnings


def _parse_row(
    row_number: int, raw: dict[str, str], image_map: dict[str, list[ParsedBatchImage]]
) -> ParsedBatchRow:
    sku = str(raw.get("SKU", "")).strip()
    barcode = str(raw.get("CodigoBarras", "")).strip()
    price_raw = str(raw.get("Precio", "")).strip()
    logistics = str(raw.get("TipoLogistica", "")).strip().lower()
    listing = str(raw.get("TipoPublicacion", "")).strip().lower()
    shipping = str(raw.get("EnvioGratis", "")).strip().lower()
    publicar = str(raw.get("Publicar", "SI")).strip().upper() or "SI"
    errors: list[str] = []
    if not sku:
        errors.append("SKU is required")
    if not barcode.isdigit():
        errors.append("CodigoBarras must be numeric")
    try:
        price = float(price_raw)
    except ValueError:
        price = 0.0
    if price <= 0:
        errors.append("Precio must be greater than 0")
    if logistics not in ACCEPTED_LOGISTICS:
        errors.append(f"TipoLogistica {logistics} is not accepted")
    if listing not in ACCEPTED_LISTING_TYPES:
        errors.append(f"TipoPublicacion {listing} is not accepted")
    if shipping not in ACCEPTED_FREE_SHIPPING:
        errors.append(f"EnvioGratis {shipping} is not accepted")
    if publicar != "SI":
        errors.append(f"Publicar is {publicar} in the Excel row")
    images = image_map.get(sku, [])
    if publicar == "SI":
        if len(images) < 3 or len(images) > 10:
            errors.append(f"SKU folder {sku} must contain between 3 and 10 images")
        for image in images:
            if image.width < 500 or image.height < 500:
                errors.append(f"{image.filename} resolution must be at least 500x500")
    if errors:
        publicar = "NO"
    return ParsedBatchRow(
        row_number=row_number,
        sku=sku,
        codigo_barras=barcode,
        price=price,
        logistics_type=logistics,
        listing_type=listing,
        free_shipping=shipping == "si",
        publicar=publicar,
        raw=raw,
        images=images,
        errors=errors,
    )


def _image_dimensions(data: bytes, *, extension: str) -> tuple[int, int]:
    if extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if extension in {".jpg", ".jpeg"}:
        return _jpeg_dimensions(data)
    if (
        extension == ".webp"
        and len(data) >= 30
        and data[0:4] == b"RIFF"
        and data[8:12] == b"WEBP"
        and data[12:16] == b"VP8X"
    ):
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return 0, 0


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        return 0, 0
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        block_length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker in {0xC0, 0xC2}:
            return (
                int.from_bytes(data[index + 7 : index + 9], "big"),
                int.from_bytes(data[index + 5 : index + 7], "big"),
            )
        index += 2 + block_length
    return 0, 0
