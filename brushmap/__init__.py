"""What can a 10 m pixel see? Mapping Texas brush species (Ashe juniper, honey mesquite) with Sentinel-1, Sentinel-2 and lidar."""
import os as _os
import sys as _sys

# Windows + conda: MKL can crash or hang on its default threading layer when GDAL's
# threads are active, and DLLs resolve wrongly when the env is not activated.
_os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
if _sys.platform == "win32":
    _bin = _os.path.join(_sys.prefix, "Library", "bin")
    if _os.path.isdir(_bin) and not _os.environ.get("PATH", "").lower().startswith(_bin.lower()):
        _os.environ["PATH"] = _bin + _os.pathsep + _os.environ.get("PATH", "")

__version__ = "0.1.0"
