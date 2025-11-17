"""Utility per generare disegni DXF a partire da immagini."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import cv2
import ezdxf
import numpy as np


@dataclass
class CADGenerationResult:
    """Risultato della generazione DXF."""

    path: str
    polylines: List[Sequence[Tuple[float, float]]]


class CADGenerationError(Exception):
    """Eccezione per errori nella generazione CAD."""


def _load_grayscale_image(data: bytes) -> np.ndarray:
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise CADGenerationError("Immagine non valida o non supportata")
    return image


def _extract_polylines(
    image: np.ndarray,
    canny_threshold1: int = 50,
    canny_threshold2: int = 150,
    approx_epsilon: float = 2.0,
) -> List[Sequence[Tuple[float, float]]]:
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    edges = cv2.Canny(blurred, threshold1=canny_threshold1, threshold2=canny_threshold2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    polylines: List[Sequence[Tuple[float, float]]] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        epsilon = max(approx_epsilon, 0.5)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        polyline = [(float(point[0][0]), float(point[0][1])) for point in approx]
        polylines.append(polyline)
    return polylines


def _write_polylines_to_dxf(
    polylines: Sequence[Sequence[Tuple[float, float]]], layer: str = "OUTLINE"
) -> str:
    doc = ezdxf.new("R2010")
    if layer not in doc.layers:
        doc.layers.add(name=layer)
    msp = doc.modelspace()

    for polyline in polylines:
        if len(polyline) < 2:
            continue
        msp.add_lwpolyline(polyline, dxfattribs={"layer": layer, "closed": True})

    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        doc.saveas(tmp.name)
        return tmp.name


def generate_cad_from_image(
    data: bytes,
    layer: str = "OUTLINE",
    canny_threshold1: int = 50,
    canny_threshold2: int = 150,
    approx_epsilon: float = 2.0,
) -> CADGenerationResult:
    """Crea un file DXF a partire da un'immagine raster."""

    image = _load_grayscale_image(data)
    polylines = _extract_polylines(
        image,
        canny_threshold1=canny_threshold1,
        canny_threshold2=canny_threshold2,
        approx_epsilon=approx_epsilon,
    )
    if not polylines:
        raise CADGenerationError("Nessun contorno rilevato nell'immagine")

    path = _write_polylines_to_dxf(polylines, layer=layer)
    return CADGenerationResult(path=path, polylines=polylines)
