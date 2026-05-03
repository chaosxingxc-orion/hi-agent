"""ProfileRegistry: register and look up business agent profiles."""

from __future__ import annotations

from hi_agent.profiles.contracts import ProfileSpec


class ProfileRegistry:
    """Central registry for business agent runtime profiles.

    Business agents register their ProfileSpec at startup.  The platform
    reads the active profile to configure stage routing, evaluator selection,
    and capability requirements — without hardcoding any of that in core.
    """

    # scope: process-internal — profile schemas are filesystem-loaded and shared across tenants in the worker process. Per-tenant profile selection happens at the registry consumer (RunManager.create_run via task_contract.profile_id). Adding tenant scoping here would require duplicate profile registration per tenant, which is not a current consumer requirement.  # noqa: E501  expiry_wave: permanent  # single-line annotation required by Track B Gap 1

    def __init__(self) -> None:
        self._profiles: dict[str, ProfileSpec] = {}

    def register(self, profile: ProfileSpec) -> None:
        """Register a profile.

        Raises:
            ValueError: If a profile with the same profile_id is already registered.
        """
        if profile.profile_id in self._profiles:
            raise ValueError(
                f"Profile {profile.profile_id!r} is already registered. "
                "Use remove() first if you need to replace it."
            )
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> ProfileSpec | None:
        """Return the profile for *profile_id*, or None if not found."""
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list[ProfileSpec]:
        """Return all registered profiles."""
        return list(self._profiles.values())

    def remove(self, profile_id: str) -> bool:
        """Remove a profile by ID. Returns True if it was present."""
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            return True
        return False

    def has(self, profile_id: str) -> bool:
        """Return True if the profile is registered."""
        return profile_id in self._profiles

    def count(self) -> int:
        """Return the number of registered profiles."""
        return len(self._profiles)

    def clear(self) -> None:
        """Remove all profiles."""
        self._profiles.clear()
