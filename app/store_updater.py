"""Microsoft Store update notification for MSIX-installed PDFApps.

When running inside a packaged (MSIX) install, the standard self-updater
(downloading PDFAppsSetup.exe from GitHub Releases) is inappropriate
because the MSIX sandbox forbids running arbitrary installers and would
otherwise result in dual installations (the Store-managed MSIX plus an
NSIS copy in %LOCALAPPDATA%\\Programs\\PDFApps).

This module:
1. Detects MSIX-packaged execution (env var or WindowsApps path).
2. Queries the Microsoft Store DisplayCatalog API for the latest
   published version of listing 9P70QGR8BSMZ.
3. Returns a tuple ``(has_update, latest_version)`` for the UI layer to
   show a non-blocking notification with a deep-link to the Store.

All network failures are swallowed and logged — an offline launch must
never block start-up or surface an error toast in the GUI.
"""

import json
import logging
import os
import sys
import urllib.request
from typing import Optional, Tuple

from app.constants import APP_VERSION

_log = logging.getLogger(__name__)

# Microsoft Store listing ID for PDFApps (apps.microsoft.com/detail/9P70QGR8BSMZ)
STORE_PRODUCT_ID = "9P70QGR8BSMZ"

# Public Storefront / DisplayCatalog API endpoint. ``bigIds`` is the
# documented parameter for "fetch product metadata by listing ID".
_DISPLAYCATALOG_URL = (
    "https://displaycatalog.mp.microsoft.com/v7.0/products"
    f"?bigIds={STORE_PRODUCT_ID}"
    "&market=US"
    "&languages=en-US"
)

_REQUEST_TIMEOUT_SECONDS = 10

# ms-windows-store:// URI scheme handled by the Store app; opens the
# product detail page directly.
_STORE_DEEP_LINK = f"ms-windows-store://pdp/?productid={STORE_PRODUCT_ID}"


def is_msix_install() -> bool:
    """Detect if PDFApps is running inside a Windows App Package (MSIX/AppX).

    Returns True for MSIX installs (Microsoft Store), False for NSIS
    installer / portable .exe / non-Windows platforms. Two indicators
    are checked because either alone has edge cases:

    * ``PACKAGE_FULL_NAME`` is set by the Windows runtime for packaged
      apps but can be unset when tooling launches the .exe outside the
      AppContainer.
    * The ``\\WindowsApps\\`` path prefix is reliable because MSIX
      packages are always extracted to ``C:\\Program Files\\WindowsApps``.
    """
    if sys.platform != "win32":
        return False
    # Method 1: env var set by Windows runtime for packaged apps.
    if os.environ.get("PACKAGE_FULL_NAME"):
        return True
    # Method 2: executable path under WindowsApps (MSIX install location).
    # Normalise with realpath so a symlinked launcher still matches.
    try:
        exe = os.path.realpath(sys.executable).lower()
    except OSError:
        exe = (sys.executable or "").lower()
    if "\\windowsapps\\" in exe or "/windowsapps/" in exe:
        return True
    return False


def _parse_version(s: str) -> Tuple[int, ...]:
    """Parse ``'1.13.16'`` or ``'1.13.16.0'`` into a comparable tuple.

    Non-numeric components are coerced to 0 so a tag like
    ``'1.13.16-beta'`` still produces a comparable tuple.
    """
    if not s:
        return (0,)
    parts = []
    for chunk in s.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def get_store_version() -> Optional[str]:
    """Query the Microsoft Store DisplayCatalog API for the latest
    published version of the PDFApps listing.

    Returns the version string (e.g. ``'1.13.16'``) or ``None`` on any
    network/parse failure — callers must treat ``None`` as "could not
    determine; do not notify".
    """
    try:
        req = urllib.request.Request(
            _DISPLAYCATALOG_URL,
            headers={"User-Agent": f"PDFApps/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _log.warning("Store version check failed: %s", exc)
        return None

    versions: list[Tuple[int, ...]] = []
    try:
        for product in data.get("Products", []) or []:
            for sku in product.get("DisplaySkuAvailabilities", []) or []:
                properties = (sku.get("Sku") or {}).get("Properties") or {}
                for pkg in properties.get("Packages", []) or []:
                    ver = pkg.get("Version")
                    if ver:
                        versions.append(_parse_version(ver))
    except Exception as exc:
        _log.warning("Store API response parse failed: %s", exc)
        return None

    if not versions:
        _log.info("Store API returned no version info")
        return None

    # Highest version published — Store may list older revisions for
    # rollback purposes.
    latest = max(versions)
    # Drop trailing .0 if present (e.g. 1.13.16.0 -> 1.13.16) so the
    # comparison with APP_VERSION ("1.13.16") matches in length.
    while len(latest) > 3 and latest[-1] == 0:
        latest = latest[:-1]
    return ".".join(str(n) for n in latest)


def check_for_store_update() -> Tuple[bool, Optional[str]]:
    """Returns ``(has_update, latest_version_str)``.

    ``(False, None)`` is returned on error or when the Store reports the
    same/older version than ``APP_VERSION``. Only meaningful when
    :func:`is_msix_install` is True; callers should guard.
    """
    latest = get_store_version()
    if not latest:
        return False, None

    current = _parse_version(APP_VERSION)
    latest_tuple = _parse_version(latest)

    has_update = latest_tuple > current
    return has_update, latest if has_update else None


def store_deep_link() -> str:
    """Returns the ``ms-windows-store://`` URI to open the listing in the Store app."""
    return _STORE_DEEP_LINK
