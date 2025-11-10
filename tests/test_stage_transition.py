from app.utility.stage_transition import StageTransitionHelper


def test_deleted_cannot_transition_directly_to_tracking_completed():
	decision = StageTransitionHelper.evaluate_transition(
		current_stage="Deleted",
		requested_stage="Tracking Completed",
		replace_item="123456",
	)

	assert decision.allowed is False
	assert decision.final_stage == "Deleted"
	assert decision.reason == "Deleted rows must move to an active stage before completion"


def test_deleted_placeholder_reactivates_to_pending_item_number():
	decision = StageTransitionHelper.evaluate_transition(
		current_stage="Deleted",
		requested_stage="Pending Clinical Readiness",
		replace_item="PENDING***123",
	)

	assert decision.allowed is True
	assert decision.final_stage == "Pending Item Number"
	assert decision.reason == "Replacement item is pending; reverting to Pending Item Number"
