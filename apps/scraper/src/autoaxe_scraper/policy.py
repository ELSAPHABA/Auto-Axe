"""Fixed source allowlists; untrusted arbitrary URLs are never accepted."""

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    url: str
    mode: str = "http"
    api_only: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("not a fixed public HTTPS source")
        host = parsed.hostname
        if (
            not host.isascii()
            or host == "localhost"
            or host.endswith((".local", ".localhost", ".internal"))
            or "." not in host
        ):
            raise ValueError("private/untrusted domain")
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("literal IP destinations prohibited")


SOURCES = {
    "cnn": SourcePolicy(
        "cnn",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        api_only=True,
    ),
    # Public /api/dashboard-data JSON was verified in the 2026-11-22
    # acquisition research; terms allow reasonable API requests, not page scraping.
    "pizzint": SourcePolicy(
        "pizzint", "https://www.pizzint.watch/api/dashboard-data", api_only=True
    ),
    "dramexchange": SourcePolicy("dramexchange", "https://www.dramexchange.com/"),
    "seibro": SourcePolicy(
        "seibro",
        "https://seibro.or.kr/websquare/control.jsp"
        "?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921",
        "browser",
    ),
    "naver": SourcePolicy("naver", "https://m.stock.naver.com/marketindex/bond/US2YT=RR"),
}


def fixed_target(source_id: str) -> SourcePolicy:
    return SOURCES[source_id]
