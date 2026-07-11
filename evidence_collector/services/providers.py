"""Safe search-provider abstractions for evidence collection.

This module deliberately contains no vendor-specific request payloads.  The
provider adapters are a small, deterministic seam around an injected
transport; without one they never make a network request.  Credentials are
used only to compute availability and are excluded from representations and
all public registry summaries.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias, runtime_checkable

from pydantic import ConfigDict, Field, ValidationError, field_validator

from ..config import SUPPORTED_PROVIDER_IDS as _SUPPORTED_PROVIDER_IDS
from ..schemas import SearchHit as _SchemaSearchHit
from ..schemas import SearchRequest as _SchemaSearchRequest


SUPPORTED_PROVIDER_IDS = tuple(_SUPPORTED_PROVIDER_IDS)


class SearchRequest(_SchemaSearchRequest):
    """Immutable request value used by provider implementations.

    The canonical schema remains in :mod:`evidence_collector.schemas`; this
    subclass adds immutability at the service boundary while retaining all of
    its validation and provider literals.
    """

    model_config = ConfigDict(frozen=True)


class SearchHit(_SchemaSearchHit):
    """Immutable evidence hit with optional provenance metadata.

    ``provider``, ``model`` and ``request_id`` are intentionally optional:
    provider transports differ in which metadata they return.  Unknown
    metadata is retained in the Pydantic model (rather than discarded), which
    makes the normalization boundary auditable without exposing credentials.
    """

    model_config = ConfigDict(frozen=True, extra="allow")
    provider: str | None = None
    model: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] | None = None

    @field_validator("provider", "model", "request_id")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Non-loggable configuration for one provider.

    The API key is an ``InitVar``: it is consumed only to compute the boolean
    availability bit and is never retained on the settings object.  In this
    repository's default adapter no transport is installed, so the key is
    never used or sent.
    """

    provider_id: str
    model: str | None = None
    base_url: str | None = None
    web_search_enabled: bool = False
    api_key: InitVar[str | None] = None
    _has_api_key: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self, api_key: str | None) -> None:
        provider_id = self.provider_id.strip().lower()
        if provider_id not in SUPPORTED_PROVIDER_IDS:
            raise ValueError(f"unsupported provider_id: {self.provider_id!r}")
        object.__setattr__(self, "provider_id", provider_id)
        for name in ("model", "base_url"):
            value = getattr(self, name)
            if isinstance(value, str):
                object.__setattr__(self, name, value.strip() or None)
        object.__setattr__(
            self,
            "_has_api_key",
            bool(isinstance(api_key, str) and api_key.strip()),
        )

    @property
    def enabled(self) -> bool:
        """Whether retrieval may even be attempted for this configuration."""

        return bool(
            self._has_api_key
            and self.model
            and self.base_url
            and self.web_search_enabled
        )

    @property
    def safe_dict(self) -> Mapping[str, Any]:
        """A credential-free representation suitable for logs/metrics."""

        return MappingProxyType(
            {
                "provider_id": self.provider_id,
                "model": self.model,
                "base_url": self.base_url,
                "web_search_enabled": self.web_search_enabled,
                "enabled": self.enabled,
            }
        )

    def __repr__(self) -> str:  # pragma: no cover - exercised by safety tests
        return (
            "ProviderSettings("
            f"provider_id={self.provider_id!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, "
            f"web_search_enabled={self.web_search_enabled!r}, "
            f"enabled={self.enabled!r})"
        )

    @classmethod
    def from_mapping(cls, provider_id: str, value: Any) -> "ProviderSettings":
        """Build settings from a mapping or an existing settings-like object."""

        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            data = dict(value)
        else:
            data = {
                name: getattr(value, name, None)
                for name in ("api_key", "model", "base_url", "web_search_enabled")
            }
            # Existing collector config exposes only a safe ``enabled`` flag.
            if data["web_search_enabled"] is None:
                data["web_search_enabled"] = getattr(value, "enabled", False)
        # Environment-style mappings are accepted as a convenience, while
        # retaining a single credential-free settings representation.
        key = data.get("api_key", data.get("API_KEY", data.get("key")))
        web_enabled = data.get(
            "web_search_enabled",
            data.get("WEB_SEARCH_ENABLED", data.get("web_search", False)),
        )
        if isinstance(web_enabled, str):
            web_enabled = web_enabled.strip().lower() == "true"
        return cls(
            provider_id=provider_id,
            api_key=key,
            model=data.get("model", data.get("MODEL")),
            base_url=data.get("base_url", data.get("BASE_URL", data.get("endpoint"))),
            web_search_enabled=bool(web_enabled),
        )

    @classmethod
    def from_environment(
        cls,
        provider_id: str,
        environ: Mapping[str, str] | None = None,
    ) -> "ProviderSettings":
        env = os.environ if environ is None else environ
        prefix = f"EVIDENCE_{provider_id.upper()}"
        enabled = (env.get(f"{prefix}_WEB_SEARCH_ENABLED") or "").strip().lower() == "true"
        return cls(
            provider_id=provider_id,
            api_key=env.get(f"{prefix}_API_KEY"),
            model=env.get(f"{prefix}_MODEL"),
            base_url=env.get(f"{prefix}_BASE_URL"),
            web_search_enabled=enabled,
        )


class DisabledProviderError(RuntimeError):
    """Raised when an unconfigured provider is asked to retrieve evidence."""


class ProviderTransportUnavailableError(RuntimeError):
    """Raised when an enabled adapter has no explicitly injected transport."""


class InvalidSearchHitError(ValueError):
    """Raised when a provider result cannot be used as quoted HTTP evidence."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Cached capability probe outcome.

    A provider is eligible only when ``eligible`` is true, which requires at
    least one normalized hit containing both an HTTP(S) URL and non-blank
    evidence quote.  ``hits`` is a tuple to prevent callers mutating cache
    state.
    """

    provider_id: str
    hits: tuple[SearchHit, ...] = ()
    eligible: bool = False
    model: str | None = None
    request_id: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def citation_bearing(self) -> bool:
        return self.eligible

    def __iter__(self):
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)


@runtime_checkable
class SearchProvider(Protocol):
    provider_id: str

    async def probe(self) -> ProbeResult: ...

    async def search(self, request: SearchRequest) -> list[SearchHit]: ...


RawTransportResult: TypeAlias = Any
AsyncTransport: TypeAlias = Callable[..., Awaitable[RawTransportResult]]


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    return None


def normalize_hit(
    raw: Any,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    request_id: str | None = None,
) -> SearchHit:
    """Validate and normalize one transport result.

    No result is accepted unless its URL is HTTP(S) and its quote contains
    non-whitespace evidence.  The function accepts the canonical schema's
    ``SearchHit`` as well as common transport dictionaries.
    """

    if isinstance(raw, SearchHit):
        data: dict[str, Any] = raw.model_dump()
    elif isinstance(raw, _SchemaSearchHit):
        data = raw.model_dump()
    else:
        mapping = _coerce_mapping(raw)
        if mapping is None:
            raise InvalidSearchHitError("search hit must be a mapping or SearchHit")
        data = dict(mapping)

    # Accept a few transport-neutral names, without prescribing any vendor
    # payload shape.
    if "quote" not in data:
        for alias in ("evidence_quote", "evidence", "snippet", "text"):
            if alias in data:
                data["quote"] = data[alias]
                break
    if not data.get("provider"):
        data["provider"] = data.get("provider_id", provider_id)
    if not data.get("model"):
        data["model"] = data.get("model_name", model)
    if not data.get("request_id"):
        data["request_id"] = data.get("requestId", request_id)

    url = data.get("url")
    # ``model_dump()`` on the canonical schema returns a Pydantic HttpUrl
    # object; converting it to text here keeps normalization compatible with
    # both canonical and transport dictionaries.
    if url is not None and not isinstance(url, str):
        url = str(url)
        data["url"] = url
    if not isinstance(url, str) or url.strip().lower().split(":", 1)[0] not in {"http", "https"}:
        raise InvalidSearchHitError("search hit requires an HTTP(S) URL")
    quote = data.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        raise InvalidSearchHitError("search hit requires a non-blank evidence quote")
    try:
        return SearchHit.model_validate(data)
    except ValidationError as exc:
        raise InvalidSearchHitError(str(exc)) from exc


def normalize_hits(
    raw_hits: Iterable[Any],
    *,
    provider_id: str | None = None,
    model: str | None = None,
    request_id: str | None = None,
    reject_invalid: bool = False,
) -> list[SearchHit]:
    """Normalize a collection, dropping malformed hits by default."""

    result: list[SearchHit] = []
    for raw in raw_hits:
        try:
            result.append(
                normalize_hit(
                    raw,
                    provider_id=provider_id,
                    model=model,
                    request_id=request_id,
                )
            )
        except InvalidSearchHitError:
            if reject_invalid:
                raise
    return result


def _extract_hits(raw: Any) -> tuple[Iterable[Any], str | None, str | None]:
    """Extract transport-neutral hit data and response metadata."""

    mapping = _coerce_mapping(raw)
    if mapping is not None:
        hits = mapping.get("hits", mapping.get("results", mapping.get("items", [])))
        if isinstance(hits, Mapping) or isinstance(hits, (str, bytes)):
            hits = [hits]
        if not isinstance(hits, Iterable):
            hits = []
        request_id = mapping.get("request_id", mapping.get("requestId", mapping.get("id")))
        model = mapping.get("model", mapping.get("model_name"))
        return hits, str(request_id) if request_id else None, str(model) if model else None
    if isinstance(raw, (str, bytes)):
        return (), None, None
    if isinstance(raw, Iterable):
        return raw, None, None
    return (), None, None


class GenericProviderAdapter:
    """Disabled-safe, payload-agnostic adapter for a named provider."""

    def __init__(
        self,
        settings: ProviderSettings,
        transport: AsyncTransport | None = None,
    ) -> None:
        self.settings = settings
        self.provider_id = settings.provider_id
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    async def _call_transport(self, request: SearchRequest) -> Any:
        if self._transport is None:
            raise ProviderTransportUnavailableError(
                f"provider '{self.provider_id}' has no injected transport; network access is disabled"
            )
        # Keep the adapter payload-neutral and do not pass credentials.  A
        # two-argument test transport may receive the safe settings object.
        try:
            signature = inspect.signature(self._transport)
            positional = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind
                in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ]
        except (TypeError, ValueError):
            positional = []
        if len(positional) >= 2:
            return await self._transport(request, self.settings.safe_dict)
        return await self._transport(request)

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        if not self.enabled:
            raise DisabledProviderError(
                f"provider '{self.provider_id}' is disabled: API key, model, base URL, "
                "and web_search_enabled are all required"
            )
        if request.provider != self.provider_id:
            raise ValueError(
                f"request provider '{request.provider}' does not match '{self.provider_id}'"
            )
        raw = await self._call_transport(request)
        raw_hits, response_request_id, response_model = _extract_hits(raw)
        return normalize_hits(
            raw_hits,
            provider_id=self.provider_id,
            model=response_model or self.settings.model,
            request_id=response_request_id,
        )[: request.max_results]

    async def probe(self) -> ProbeResult:
        if not self.enabled:
            raise DisabledProviderError(
                f"provider '{self.provider_id}' is disabled: API key, model, base URL, "
                "and web_search_enabled are all required"
            )
        request = SearchRequest(
            provider=self.provider_id,
            model=self.settings.model,
            query="provider capability probe",
            max_results=1,
            prompt_version="provider-probe-v1",
        )
        hits = await self.search(request)
        return ProbeResult(
            provider_id=self.provider_id,
            hits=tuple(hits),
            eligible=bool(hits),
            model=self.settings.model,
            request_id=hits[0].request_id if hits else None,
        )


class StaticSearchProvider:
    """Deterministic in-memory provider for tests and offline development."""

    def __init__(
        self,
        provider_id: str = "deepseek",
        hits: Sequence[Any] = (),
        *,
        model: str | None = None,
        request_id: str | None = None,
    ) -> None:
        provider_id = provider_id.strip().lower()
        if provider_id not in SUPPORTED_PROVIDER_IDS:
            raise ValueError(f"unsupported provider_id: {provider_id!r}")
        self.provider_id = provider_id
        self.model = model
        self.request_id = request_id
        self._hits = tuple(
            normalize_hits(
                hits,
                provider_id=provider_id,
                model=model,
                request_id=request_id,
                reject_invalid=True,
            )
        )

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        if request.provider != self.provider_id:
            raise ValueError(
                f"request provider '{request.provider}' does not match '{self.provider_id}'"
            )
        return list(self._hits[: request.max_results])

    async def probe(self) -> ProbeResult:
        hits = self._hits[:1]
        return ProbeResult(
            provider_id=self.provider_id,
            hits=hits,
            eligible=bool(hits),
            model=self.model,
            request_id=hits[0].request_id if hits else self.request_id,
        )


def provider_adapter(
    provider_id: str,
    settings: ProviderSettings | Mapping[str, Any] | Any,
    *,
    transport: AsyncTransport | None = None,
) -> GenericProviderAdapter:
    """Factory for all supported IDs; no vendor payload is guessed."""

    normalized = provider_id.strip().lower()
    if normalized not in SUPPORTED_PROVIDER_IDS:
        raise ValueError(f"unsupported provider_id: {provider_id!r}")
    return GenericProviderAdapter(
        ProviderSettings.from_mapping(normalized, settings),
        transport=transport,
    )


class ProviderRegistry:
    """Registry of configured adapters and cached capability probes."""

    def __init__(
        self,
        settings: Mapping[str, ProviderSettings | Mapping[str, Any] | Any] | None = None,
        *,
        transports: Mapping[str, AsyncTransport] | None = None,
    ) -> None:
        settings = settings or {}
        transports = transports or {}
        normalized_settings = {
            provider_id: ProviderSettings.from_mapping(
                provider_id,
                settings.get(provider_id, {}),
            )
            for provider_id in SUPPORTED_PROVIDER_IDS
        }
        self._settings = MappingProxyType(normalized_settings)
        self._providers = MappingProxyType(
            {
                provider_id: provider_adapter(
                    provider_id,
                    provider_settings,
                    transport=transports.get(provider_id),
                )
                for provider_id, provider_settings in normalized_settings.items()
            }
        )
        self._probe_cache: dict[str, ProbeResult] = {}

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        transports: Mapping[str, AsyncTransport] | None = None,
    ) -> "ProviderRegistry":
        return cls(
            {
                provider_id: ProviderSettings.from_environment(provider_id, environ)
                for provider_id in SUPPORTED_PROVIDER_IDS
            },
            transports=transports,
        )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | Any,
        *,
        transports: Mapping[str, AsyncTransport] | None = None,
    ) -> "ProviderRegistry":
        if isinstance(config, Mapping) and any(
            key.startswith("EVIDENCE_") for key in config
        ):
            return cls.from_environment(config, transports=transports)
        values = config.providers if hasattr(config, "providers") else config
        return cls(values, transports=transports)

    @property
    def providers(self) -> Mapping[str, SearchProvider]:
        return self._providers

    @property
    def settings(self) -> Mapping[str, ProviderSettings]:
        return self._settings

    @property
    def enabled_provider_ids(self) -> tuple[str, ...]:
        return tuple(pid for pid, p in self._providers.items() if p.enabled)

    @property
    def eligible_provider_ids(self) -> tuple[str, ...]:
        return tuple(pid for pid, result in self._probe_cache.items() if result.eligible)

    def get(self, provider_id: str) -> SearchProvider:
        try:
            return self._providers[provider_id.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"unsupported provider_id: {provider_id!r}") from exc

    def __getitem__(self, provider_id: str) -> SearchProvider:
        return self.get(provider_id)

    def __iter__(self):
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    async def probe(self, provider_id: str, *, force: bool = False) -> ProbeResult:
        normalized = provider_id.strip().lower()
        provider = self.get(normalized)
        if not force and normalized in self._probe_cache:
            return self._probe_cache[normalized]
        raw_result = await provider.probe()
        if isinstance(raw_result, ProbeResult):
            result = raw_result
        else:
            # Be liberal for third-party protocol implementations returning a
            # plain sequence of hits.
            result = ProbeResult(
                provider_id=normalized,
                hits=tuple(
                    normalize_hits(
                        raw_result if isinstance(raw_result, Iterable) else (),
                        provider_id=normalized,
                        model=self._settings[normalized].model,
                    )
                ),
                model=self._settings[normalized].model,
            )
            result = ProbeResult(
                provider_id=result.provider_id,
                hits=result.hits,
                eligible=bool(result.hits),
                model=result.model,
            )
        # Eligibility is derived from validated citations, not model presence.
        normalized_hits = tuple(
            normalize_hits(
                result.hits,
                provider_id=normalized,
                model=result.model or self._settings[normalized].model,
                request_id=result.request_id,
            )
        )
        result = ProbeResult(
            provider_id=normalized,
            hits=normalized_hits,
            eligible=bool(normalized_hits),
            model=result.model or self._settings[normalized].model,
            request_id=result.request_id or (normalized_hits[0].request_id if normalized_hits else None),
            checked_at=result.checked_at,
        )
        self._probe_cache[normalized] = result
        return result

    def is_eligible(self, provider_id: str) -> bool:
        result = self._probe_cache.get(provider_id.strip().lower())
        return bool(result and result.eligible)

    def clear_probe_cache(self) -> None:
        self._probe_cache.clear()

    def __repr__(self) -> str:
        enabled = ", ".join(self.enabled_provider_ids) or "none"
        return f"ProviderRegistry(enabled=({enabled}), providers={SUPPORTED_PROVIDER_IDS!r})"


def create_provider_registry(
    config: Mapping[str, Any] | Any | None = None,
    *,
    transports: Mapping[str, AsyncTransport] | None = None,
) -> ProviderRegistry:
    """Convenience factory using environment configuration by default."""

    return (
        ProviderRegistry.from_environment(transports=transports)
        if config is None
        else ProviderRegistry.from_config(config, transports=transports)
    )


# Common aliases make the factory discoverable without coupling callers to a
# particular naming convention.
build_provider_registry = create_provider_registry
make_provider = provider_adapter


__all__ = [
    "SUPPORTED_PROVIDER_IDS",
    "SearchRequest",
    "SearchHit",
    "SearchProvider",
    "ProviderSettings",
    "ProviderRegistry",
    "ProbeResult",
    "StaticSearchProvider",
    "GenericProviderAdapter",
    "DisabledProviderError",
    "ProviderTransportUnavailableError",
    "InvalidSearchHitError",
    "normalize_hit",
    "normalize_hits",
    "provider_adapter",
    "make_provider",
    "create_provider_registry",
    "build_provider_registry",
]
