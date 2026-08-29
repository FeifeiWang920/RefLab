"""
CATIA V5 COM bridge.

Import strategy for surface STEP (sewn shell / open faces):
  CATIA places surface geometry into a Geometrical Set / HybridBody,
  NOT into PartBody.  Searching only for Body therefore fails with
  "Open.Part".  We search HybridShape / Face / Shell / Body and paste
  into a dedicated HybridBody named e.g. MF_Reflector.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, List
import os
import sys
import tempfile
import time


class CatiaState(str, Enum):
    UNAVAILABLE = "unavailable"
    NOT_RUNNING = "not_running"
    NO_ACTIVE_DOC = "no_active_doc"
    NOT_PART = "not_part"
    PART_READY = "part_ready"


@dataclass
class CatiaStatus:
    state: CatiaState
    message: str
    document_name: str = ""
    catia_version: str = ""

    @property
    def ok(self) -> bool:
        return self.state == CatiaState.PART_READY


def is_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def _get_catia():
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    try:
        return win32com.client.GetActiveObject("CATIA.Application")
    except Exception:
        try:
            return win32com.client.Dispatch("CATIA.Application")
        except Exception:
            return None


def detect_catia() -> CatiaStatus:
    if not is_available():
        return CatiaStatus(
            state=CatiaState.UNAVAILABLE,
            message="CATIA COM 不可用（需要 Windows + pywin32）",
        )
    try:
        catia = _get_catia()
    except Exception as exc:
        return CatiaStatus(
            state=CatiaState.NOT_RUNNING,
            message=f"无法连接 CATIA: {exc}",
        )
    if catia is None:
        return CatiaStatus(
            state=CatiaState.NOT_RUNNING,
            message="CATIA 未启动",
        )

    version = ""
    try:
        version = str(getattr(catia, "Version", "") or "")
    except Exception:
        pass

    try:
        if catia.Documents.Count < 1:
            return CatiaStatus(
                state=CatiaState.NO_ACTIVE_DOC,
                message="CATIA 已启动，但没有打开的文档",
                catia_version=version,
            )
        doc = catia.ActiveDocument
        name = str(doc.Name)
        try:
            _ = doc.Part
            return CatiaStatus(
                state=CatiaState.PART_READY,
                message=f"已连接到 Part: {name}",
                document_name=name,
                catia_version=version,
            )
        except Exception:
            return CatiaStatus(
                state=CatiaState.NOT_PART,
                message=f"当前文档不是 Part（{name}），请打开 .CATPart",
                document_name=name,
                catia_version=version,
            )
    except Exception as exc:
        return CatiaStatus(
            state=CatiaState.NO_ACTIVE_DOC,
            message=f"读取 CATIA 文档失败: {exc}",
            catia_version=version,
        )


# ---------------------------------------------------------------------------
# Selection helpers – surface STEP lands in HybridBody, not PartBody
# ---------------------------------------------------------------------------

_SEARCH_QUERIES = [
    "Name=*,all",
    "Type=HybridShape,all",
    "Type=Face,all",
    "Type=Shell,all",
    "Type=Surface,all",
    "Type=Body,all",
    "Type=Shape,all",
    "Type=GSMTool,all",
]


def _select_geometry(doc) -> int:
    """Select the actual imported geometry in *doc*. Returns selection count."""
    doc.Activate()
    sel = doc.Selection
    sel.Clear()

    # Prefer explicit HybridShapes. A broad Selection.Search can also select
    # Part / planes / containers, which does not produce a useful clipboard.
    try:
        part = doc.Part
        count = 0
        for i in range(1, part.HybridBodies.Count + 1):
            hybrid_body = part.HybridBodies.Item(i)
            for j in range(1, hybrid_body.HybridShapes.Count + 1):
                sel.Add(hybrid_body.HybridShapes.Item(j))
                count += 1
        if count:
            return count
    except Exception:
        pass

    for q in _SEARCH_QUERIES:
        try:
            sel.Search(q)
            if sel.Count > 0:
                return int(sel.Count)
        except Exception:
            continue
    # Fallback: try to add MainBody / HybridBodies explicitly
    try:
        part = doc.Part
        try:
            sel.Add(part.MainBody)
        except Exception:
            pass
        try:
            hbs = part.HybridBodies
            for i in range(1, hbs.Count + 1):
                try:
                    sel.Add(hbs.Item(i))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            bodies = part.Bodies
            for i in range(1, bodies.Count + 1):
                try:
                    sel.Add(bodies.Item(i))
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    return int(sel.Count)


def _ensure_hybrid_body(part, name: str = "MF_Reflector"):
    """Get or create a HybridBody (geometrical set) with the given name."""
    hbs = part.HybridBodies
    try:
        return hbs.Item(name)
    except Exception:
        pass
    hb = hbs.Add()
    try:
        hb.Name = name
    except Exception:
        pass
    return hb


def _close_doc(catia, doc) -> None:
    try:
        doc.Close()
    except Exception:
        try:
            catia.Documents.Item(doc.Name).Close()
        except Exception:
            pass


def _convert_step_to_catpart(catia, stp_path: Path) -> tuple[Any, Path]:
    """
    Convert an opened STEP document to a temporary CATPart document.

    CATIA's automation API can expose a raw STEP document as an `Open`
    document without `Part`/`Product`; Selection.Search then finds nothing.
    Exporting it to CATPart first creates a normal PartDocument whose faces,
    shells, and bodies can be selected and copied reliably.
    """
    step_doc = None
    fd, catpart_str = tempfile.mkstemp(prefix="mf_reflector_", suffix=".CATPart")
    os.close(fd)
    catpart_path = Path(catpart_str)
    # ExportData expects a destination that does not already exist.
    catpart_path.unlink(missing_ok=True)

    try:
        step_doc = catia.Documents.Read(str(stp_path))
        step_doc.ExportData(str(catpart_path), "CATPart")
    except Exception as exc:
        raise RuntimeError(f"STEP 转换 CATPart 失败: {exc}") from exc
    finally:
        if step_doc is not None:
            _close_doc(catia, step_doc)

    try:
        import win32com.client
        # Open returns a document; wrap with dynamic Dispatch for late-bound COM.
        raw = catia.Documents.Open(str(catpart_path))
        try:
            catpart_doc = win32com.client.dynamic.Dispatch(raw)
        except Exception:
            catpart_doc = raw
        # Let CATIA finish building the translated feature tree.
        time.sleep(0.5)
        return catpart_doc, catpart_path
    except Exception as exc:
        catpart_path.unlink(missing_ok=True)
        raise RuntimeError(f"打开转换后的 CATPart 失败: {exc}") from exc


def import_step_to_active_part(
    stp_path: str | Path,
    *,
    body_name: str = "MF_Reflector",
    hide_construction: bool = True,
) -> CatiaStatus:
    """
    Import a (surface) STEP into the active CATIA Part as one geometrical set.

    Surface / shell STEP files do NOT create a PartBody; they appear as
    HybridShapes.  We therefore:
      1. Open the STEP
      2. Select HybridShape / Face / Shell / Body
      3. Copy
      4. Paste into a HybridBody named *body_name* in the target Part
      5. Close the temporary document
    """
    stp_path = Path(stp_path).resolve()
    if not stp_path.exists():
        return CatiaStatus(
            state=CatiaState.UNAVAILABLE,
            message=f"STEP 文件不存在: {stp_path}",
        )

    status = detect_catia()
    if not status.ok:
        return status

    try:
        catia = _get_catia()
        if catia is None:
            return CatiaStatus(
                state=CatiaState.NOT_RUNNING,
                message="CATIA 连接丢失",
            )

        target_doc = catia.ActiveDocument
        try:
            target_part = target_doc.Part
        except Exception:
            return CatiaStatus(
                state=CatiaState.NOT_PART,
                message="当前活动文档不是 Part",
                document_name=str(getattr(target_doc, "Name", "")),
            )
        target_name = str(target_doc.Name)

        # ---- Open STEP (may be PartDocument or ProductDocument) ----
        prev_alerts = True
        try:
            prev_alerts = catia.DisplayFileAlerts
            catia.DisplayFileAlerts = False
        except Exception:
            pass

        tmp_doc = None
        temp_catpart: Path | None = None
        try:
            try:
                # A raw STEP COM document can be exposed as an `Open` document
                # without Part/Product. Convert it to a temporary CATPart first;
                # this makes Selection.Search and Copy/Paste deterministic.
                tmp_doc, temp_catpart = _convert_step_to_catpart(catia, stp_path)
            except Exception as open_exc:
                return CatiaStatus(
                    state=CatiaState.NOT_PART,
                    message=str(open_exc),
                    document_name=target_name,
                )

            n_sel = _select_geometry(tmp_doc)
            if n_sel < 1:
                # Last attempt: select everything visible
                try:
                    sel = tmp_doc.Selection
                    sel.Clear()
                    sel.Search("Name=*")
                    n_sel = int(sel.Count)
                except Exception:
                    pass

            if n_sel < 1:
                return CatiaStatus(
                    state=CatiaState.NOT_PART,
                    message=(
                        "转换后的 CATPart 中未找到几何。"
                        f"STEP 文件: {stp_path}"
                    ),
                    document_name=target_name,
                )

            sel = tmp_doc.Selection
            sel.Copy()

            # ---- Paste into target HybridBody ----
            target_doc.Activate()
            hb = _ensure_hybrid_body(target_part, body_name)

            sel = target_doc.Selection
            sel.Clear()
            try:
                sel.Add(hb)
            except Exception:
                pass

            pasted = False
            for mode in (
                "CATPrtResultWithOutLink",
                "CATPrtResult",
                "CATPrtResultWithLink",
            ):
                try:
                    sel.Clear()
                    try:
                        sel.Add(hb)
                    except Exception:
                        pass
                    sel.PasteSpecial(mode)
                    pasted = True
                    break
                except Exception:
                    continue

            if not pasted:
                try:
                    sel.Clear()
                    try:
                        sel.Add(hb)
                    except Exception:
                        pass
                    sel.Paste()
                    pasted = True
                except Exception as paste_exc:
                    raise RuntimeError(f"粘贴失败: {paste_exc}") from paste_exc

            try:
                target_part.Update()
            except Exception:
                pass

        finally:
            if tmp_doc is not None:
                _close_doc(catia, tmp_doc)
            if temp_catpart is not None:
                temp_catpart.unlink(missing_ok=True)
            try:
                catia.DisplayFileAlerts = prev_alerts
            except Exception:
                pass

        return CatiaStatus(
            state=CatiaState.PART_READY,
            message=(
                f"已将反射面导入 Part「{target_name}」"
                f"→ 几何图形集「{body_name}」"
            ),
            document_name=target_name,
            catia_version=status.catia_version,
        )

    except Exception as exc:
        return CatiaStatus(
            state=CatiaState.NOT_PART,
            message=f"导入 STEP 失败: {exc}",
            document_name=status.document_name,
            catia_version=status.catia_version,
        )


