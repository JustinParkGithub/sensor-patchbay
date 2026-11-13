"""Which CA certificates HTTPS requests trust.

A frozen app's embedded OpenSSL looks for CA certificates at a path baked in on
the build machine (e.g. ``~/miniconda3/ssl/cert.pem``), which doesn't exist on
the user's machine, so every HTTPS request fails with CERTIFICATE_VERIFY_FAILED.
The app therefore ships certifi's ``cacert.pem`` and points everything at it.

From a source checkout certifi is optional: without it the system defaults are
used, as before. ``SSL_CERT_FILE``, when set to a file that exists, always wins.
Verification is never turned off.
"""

from __future__ import annotations

import os
import ssl


def _certifi_path() -> str | None:
    try:
        import certifi
    except ImportError:
        return None
    path = certifi.where()
    return path if os.path.isfile(path) else None


def ca_file() -> str | None:
    """The CA bundle in use: ``SSL_CERT_FILE`` if it exists, else certifi's, else None
    (OpenSSL's compiled-in default)."""
    env = os.environ.get("SSL_CERT_FILE", "").strip()
    if env and os.path.isfile(env):
        return env
    return _certifi_path()


def install_default() -> None:
    """At startup, before any network call: point ``SSL_CERT_FILE`` at the bundled
    CA file unless it already names one that exists. Covers any library or
    subprocess (e.g. a module's ``requests``) that reads the environment."""
    env = os.environ.get("SSL_CERT_FILE", "").strip()
    if env and os.path.isfile(env):
        return
    path = _certifi_path()
    if path:
        os.environ["SSL_CERT_FILE"] = path


def make_ssl_context() -> ssl.SSLContext:
    """A verifying client context using :func:`ca_file`."""
    return ssl.create_default_context(cafile=ca_file())


def describe() -> str:
    """For error messages: which CA file is in use and whether it exists."""
    path = ca_file()
    if path is None:
        paths = ssl.get_default_verify_paths()
        path = paths.cafile or paths.openssl_cafile
        return f"CA file: OpenSSL default {path} ({'exists' if os.path.isfile(path) else 'MISSING'}; certifi not installed)"
    return f"CA file: {path} ({'exists' if os.path.isfile(path) else 'MISSING'})"
