"""Utility helpers for managing ItemLink stage transitions.

This module centralizes the canonical stage list and their allowed
transitions so that both single-row updates and upcoming batch
operations share the exact same logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

CANONICAL_STAGES: list[str] = [
	"Tracking - Discontinued",
	"Pending Item Number",
	"Pending Clinical Readiness",
	"Tracking - Item Transition",
	"Deleted",
	"Tracking Completed",
]


class StageTransitionError(ValueError):
	"""Raised when an invalid transition is requested."""


@dataclass(frozen=True)
class TransitionDecision:
	"""Result of evaluating a stage change request."""

	allowed: bool
	requested_stage: str
	final_stage: str
	reason: str | None = None

	@property
	def changed(self) -> bool:
		return self.allowed and self.final_stage != self.requested_stage


class StageTransitionHelper:
	"""Encapsulates the stage transition rules for ItemLink records."""

	STAGES = CANONICAL_STAGES
	_PENDING_PREFIX = "PENDING***"

	# Base adjacency (including identity transitions) for canonical stages.
	# Any stage not explicitly present defaults to being able to transition to
	# every canonical stage.
	_BASE_TRANSITIONS: Mapping[str, set[str]] = {
		"Tracking - Discontinued": {
			"Tracking - Discontinued",
			"Deleted",
			"Tracking Completed",
		},
		"Pending Item Number": {
			"Pending Item Number",
			"Pending Clinical Readiness",
			"Deleted",
		},
		"Pending Clinical Readiness": {
			"Pending Clinical Readiness",
			"Deleted",
			"Tracking - Item Transition",
		},
		"Tracking - Item Transition": {
			"Pending Clinical Readiness",
			"Deleted",
			"Tracking Completed",
		},
		"Deleted": {
			"Deleted",
			"Tracking - Discontinued",
			"Pending Item Number",
			"Pending Clinical Readiness",
			"Tracking - Item Transition",
		},
		"Tracking Completed": {
			"Tracking Completed",
		},
	}

	@classmethod
	def canonical_stage(cls, stage: str | None) -> str | None:
		if not stage:
			return None
		stage = stage.strip()
		return stage if stage in cls.STAGES else None

	@classmethod
	def is_valid_stage(cls, stage: str | None) -> bool:
		return cls.canonical_stage(stage) is not None

	@classmethod
	def allowed_targets(
		cls,
		current_stage: str | None,
		replace_item: str | None = None,
	) -> set[str]:
		current = cls.canonical_stage(current_stage)
		if current is None:
			return set(cls.STAGES)
		allowed = cls._BASE_TRANSITIONS.get(current)
		if allowed is None:
			return set(cls.STAGES)
		return set(allowed)

	@classmethod
	def evaluate_transition(
		cls,
		current_stage: str | None,
		requested_stage: str | None,
		*,
		replace_item: str | None = None,
	) -> TransitionDecision:
		current = cls.canonical_stage(current_stage)
		desired = cls.canonical_stage(requested_stage)

		if desired is None:
			return TransitionDecision(
				allowed=False,
				requested_stage=requested_stage or "",
				final_stage=current_stage or "",
				reason="Invalid stage value",
			)

		allowed_targets = cls.allowed_targets(current_stage, replace_item)
		if desired not in allowed_targets:
			reason = "Requested transition is not permitted"
			if current == "Tracking Completed" and desired != current:
				reason = "Tracking Completed is final; archive the row and add a new one to revive it"
			elif current == "Deleted" and desired == "Tracking Completed":
				reason = "Deleted rows must move to an active stage before completion"
			return TransitionDecision(
				allowed=False,
				requested_stage=desired,
				final_stage=current_stage or "",
				reason=reason,
			)

		final_stage = desired

		if current == "Deleted" and desired != "Tracking Completed":
			final_stage = cls._resolve_deleted_transition(desired, replace_item)

		return TransitionDecision(
			allowed=True,
			requested_stage=desired,
			final_stage=final_stage,
			reason=None if final_stage == desired else cls._deleted_adjustment_reason(final_stage),
		)

	@classmethod
	def _resolve_deleted_transition(cls, desired: str, replace_item: str | None) -> str:
		if desired == "Deleted":
			return desired
		if replace_item is None or str(replace_item).strip() == "":
			return "Tracking - Discontinued"
		normalized = str(replace_item).strip().upper()
		if normalized.startswith(cls._PENDING_PREFIX):
			return "Pending Item Number"
		return desired

	@classmethod
	def _deleted_adjustment_reason(cls, final_stage: str) -> str:
		if final_stage == "Tracking - Discontinued":
			return "Replacement item missing; reverting to Tracking - Discontinued"
		if final_stage == "Pending Item Number":
			return "Replacement item is pending; reverting to Pending Item Number"
		return "Stage adjusted due to Deleted transition rules"

	@classmethod
	def filter_valid_stages(cls, stages: Iterable[str]) -> list[str]:
		return [stage for stage in stages if cls.is_valid_stage(stage)]
