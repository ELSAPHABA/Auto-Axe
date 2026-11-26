from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Phase 0 deliberately refuses non-fixture environments."""

    model_config = SettingsConfigDict(env_prefix="AUTOAXE_", extra="ignore")
    environment: Literal["fixture"] = "fixture"
    live_enabled: Literal[False] = False
    external_mcp_enabled: Literal[False] = False

    @field_validator("live_enabled", "external_mcp_enabled", mode="before")
    @classmethod
    def explicit_false(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() == "false":
            return False
        # Reject integer zero and every other truthy or ambiguous setting.
        if value is not False:
            raise ValueError("Phase 0 requires explicit false")
        return value
