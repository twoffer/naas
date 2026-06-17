"""Protocol adapter implementations for the Identity Normalization Service.

Re-exports the three concrete adapters so the composition root can import them
from the package level (e.g., ``from app.adapters import OidcAdapter``).
"""

from app.adapters.ldap import LdapAdapter
from app.adapters.oidc import OidcAdapter
from app.adapters.saml import SamlAdapter

__all__ = ["LdapAdapter", "OidcAdapter", "SamlAdapter"]
